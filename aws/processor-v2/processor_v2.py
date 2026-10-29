"""
BioFastCheckProcessorV2  -  S3-triggered FASTA quality gate + primer scan.

Flow: S3 upload -> this Lambda streams the file -> QC gate -> (primer scan result
only counts if the gate passed) -> DynamoDB record -> SNS email.

Statuses written to DynamoDB:
  VALID             passed the gate, no primer/motif found
  FLAGGED_POSITIVE  passed the gate AND a target primer/motif was found
  FAILED_QC         readable FASTA but bad quality (too many Ns, fragmented, odd GC, too short)
  INVALID           not a usable nucleotide FASTA (empty, no header, protein/garbage)

No third-party libraries needed (pure Python + boto3, which Lambda already provides).
"""
import hashlib
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")

PROCESSOR_VERSION = "v2"
IUPAC_OTHER = "RYKMSWBDHV"          # ambiguous codes besides N
_COMP = str.maketrans("ACGT", "TGCA")


# ----------------------------------------------------------------- config
def load_config():
    return {
        "table": os.environ.get("TABLE_NAME", "BioFastCheckResults"),
        "topic": os.environ.get("SNS_TOPIC_ARN", ""),
        "max_ambiguous_pct": float(os.environ.get("MAX_AMBIGUOUS_PERCENT", "5")),
        "max_invalid_pct": float(os.environ.get("MAX_INVALID_PERCENT", "1")),
        "gc_min": float(os.environ.get("GC_MIN", "20")),
        "gc_max": float(os.environ.get("GC_MAX", "80")),
        "max_sequences": int(os.environ.get("MAX_SEQUENCES", "100")),
        "min_length": int(os.environ.get("MIN_SEQUENCE_LENGTH", "50")),
        # "NAME:SEQUENCE,NAME2:SEQUENCE2"  (10-15 bp each). DEMO value - replace with your real target.
        "primers": os.environ.get("PRIMER_MOTIFS", "DEMO_MOTIF:ATGGCGTACGTTAGC"),
    }


def parse_primers(spec):
    """Return {name: (forward, reverse_complement)}; both strands are scanned."""
    motifs = {}
    for item in filter(None, (p.strip() for p in spec.split(","))):
        name, _, seq = item.partition(":")
        seq = seq.strip().upper()
        if not name or not seq or set(seq) - set("ACGT"):
            log.warning("Ignoring bad primer entry %r (use NAME:ACGT-sequence)", item)
            continue
        if not 10 <= len(seq) <= 15:
            log.warning("Primer %s is %d bp (expected 10-15) - using it anyway", name, len(seq))
        motifs[name.strip()] = (seq, seq.translate(_COMP)[::-1])
    return motifs


def count_overlapping(text, pattern):
    n, start = 0, 0
    while True:
        i = text.find(pattern, start)
        if i == -1:
            return n
        n += 1
        start = i + 1


# --------------------------------------------------------------- analysis
def analyze(lines, motifs):
    """Single streaming pass over FASTA lines (bytes or str)."""
    counts = Counter()
    hits = Counter()
    n_seq = total = 0
    saw_header = seq_before_header = False
    tail = ""
    longest = cur = 0
    max_motif = max((len(f) for f, _ in motifs.values()), default=0)

    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith(">"):
            longest = max(longest, cur)
            cur, tail = 0, ""            # motifs must not span two records
            n_seq += 1
            saw_header = True
            continue
        if not saw_header:
            seq_before_header = True
        seq = line.upper()
        counts.update(seq)
        total += len(seq)
        cur += len(seq)
        if motifs:
            buf = tail + seq              # carry-over so motifs split across lines are found
            for name, (fwd, rev) in motifs.items():
                hits[name] += count_overlapping(buf, fwd)
                if rev != fwd:
                    hits[name] += count_overlapping(buf, rev)
            tail = buf[-(max_motif - 1):] if max_motif > 1 else ""
    longest = max(longest, cur)

    a, c, g, t, n = (counts[x] for x in "ACGTN")
    other_iupac = sum(counts[x] for x in IUPAC_OTHER)
    invalid = total - (a + c + g + t + n + other_iupac)
    return {
        "total": total, "n_seq": n_seq, "longest": longest,
        "A": a, "C": c, "G": g, "T": t, "N": n,
        "ambiguous": n + other_iupac, "invalid": invalid,
        "saw_header": saw_header, "seq_before_header": seq_before_header,
        "hits": {k: v for k, v in hits.items() if v > 0},
    }


def pct(part, whole):
    return round(part / whole * 100, 2) if whole else 0.0


def evaluate(m, cfg):
    """Quality gate. Returns (status, qc_flags, primer_hits_to_report, metrics)."""
    total = m["total"]
    gc = pct(m["G"] + m["C"], total)               # paper formula: (G+C)/Total Length x 100
    ambiguous_pct = pct(m["ambiguous"], total)
    invalid_pct = pct(m["invalid"], total)
    metrics = {"GC_Content": gc, "Ambiguous_Percent": ambiguous_pct}

    malformed = []
    if total == 0:
        malformed.append("EMPTY_OR_NO_SEQUENCE")
    else:
        if not m["saw_header"] or m["seq_before_header"]:
            malformed.append("MISSING_FASTA_HEADER")
        if invalid_pct > cfg["max_invalid_pct"]:
            malformed.append("NON_NUCLEOTIDE_CONTENT")
    if malformed:
        return "INVALID", malformed, {}, metrics

    flags = []
    if total < cfg["min_length"]:
        flags.append("TOO_SHORT")
    if ambiguous_pct > cfg["max_ambiguous_pct"]:
        flags.append("HIGH_AMBIGUOUS_BASES")
    if m["n_seq"] > cfg["max_sequences"]:
        flags.append("FRAGMENTED")
    if gc < cfg["gc_min"]:
        flags.append("LOW_GC")
    elif gc > cfg["gc_max"]:
        flags.append("HIGH_GC")
    if flags:
        return "FAILED_QC", flags, {}, metrics           # gate halts: primer result discarded

    if m["hits"]:
        return "FLAGGED_POSITIVE", [], m["hits"], metrics
    return "VALID", [], {}, metrics


# ----------------------------------------------------------------- output
def build_item(bucket, key, etag, m, status, flags, hits, metrics):
    file_id = hashlib.sha256(f"{bucket}/{key}/{etag}".encode()).hexdigest()[:20]
    return {
        "FileID": file_id,                      # deterministic -> S3 retries can't create duplicates
        "SourceFile": key,
        "Sequence_Length": m["total"],
        "Num_Sequences": m["n_seq"],
        "Base_A": m["A"], "Base_T": m["T"], "Base_C": m["C"], "Base_G": m["G"], "Base_N": m["N"],
        "Unknown_Bases": m["total"] - (m["A"] + m["T"] + m["C"] + m["G"]),   # same definition as the old processor
        "GC_Content": Decimal(str(metrics["GC_Content"])),
        "Ambiguous_Percent": Decimal(str(metrics["Ambiguous_Percent"])),
        "Status": status,
        "Flags": flags,
        "Primer_Hits": hits,
        "Downstream_Ready": status in ("VALID", "FLAGGED_POSITIVE"),
        "Timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "Processor_Version": PROCESSOR_VERSION,
    }


def build_email(item):
    name = item["SourceFile"].split("/")[-1]
    lines = [
        "Bio-FastCheck analysis report",
        f"File:            {name}",
        f"Status:          {item['Status']}",
        f"Sequences:       {item['Num_Sequences']}",
        f"Total length:    {item['Sequence_Length']} bp",
        f"GC content:      {item['GC_Content']}%",
        f"Ambiguous bases: {item['Ambiguous_Percent']}%  (unknown total: {item['Unknown_Bases']})",
        f"Composition:     A={item['Base_A']} T={item['Base_T']} C={item['Base_C']} G={item['Base_G']} N={item['Base_N']}",
    ]
    if item["Flags"]:
        lines.append("Quality flags:   " + ", ".join(item["Flags"]))
        lines.append("Action:          Sample halted - do not send to BLAST/alignment.")
    if item["Primer_Hits"]:
        lines.append("Primer matches:  " + ", ".join(f"{k} x{v}" for k, v in item["Primer_Hits"].items()))
    lines.append(f"Reference ID:    {item['FileID']}")
    subject = f"Bio-FastCheck [{item['Status']}] {name}"
    return subject.encode("ascii", "ignore").decode()[:100], "\n".join(lines)


# ---------------------------------------------------------------- handler
def process_object(bucket, key, etag, cfg):
    obj = s3.get_object(Bucket=bucket, Key=key)
    m = analyze(obj["Body"].iter_lines(), parse_primers(cfg["primers"]))
    status, flags, hits, metrics = evaluate(m, cfg)
    item = build_item(bucket, key, etag or obj.get("ETag", ""), m, status, flags, hits, metrics)

    try:
        dynamodb.Table(cfg["table"]).put_item(
            Item=item, ConditionExpression="attribute_not_exists(FileID)")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            log.info("Duplicate event for %s - already processed, skipping email", key)
            return {**item, "duplicate": True}
        raise

    if cfg["topic"]:
        try:
            subject, body = build_email(item)
            sns.publish(TopicArn=cfg["topic"], Subject=subject, Message=body)
        except Exception:
            log.exception("SNS publish failed (result is already saved in DynamoDB)")
    log.info("%s -> %s %s", key, status, flags)
    return item


def lambda_handler(event, context):
    cfg = load_config()
    results = []
    for rec in event.get("Records", []):
        if not rec.get("eventName", "ObjectCreated").startswith("ObjectCreated"):
            continue
        bucket = rec["s3"]["bucket"]["name"]
        key = unquote_plus(rec["s3"]["object"]["key"])
        etag = rec["s3"]["object"].get("eTag") or rec["s3"]["object"].get("sequencer", "")
        item = process_object(bucket, key, etag, cfg)
        results.append({"key": key, "status": item["Status"], "flags": item["Flags"]})
    return {"processed": results}
