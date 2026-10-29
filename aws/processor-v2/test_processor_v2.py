"""Local test: pip install moto boto3 ; python test_processor_v2.py   (no AWS account needed)"""
import json, os, random, sys
os.environ.update(AWS_DEFAULT_REGION="eu-north-1", AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="y")
import boto3
from moto import mock_aws

random.seed(1)
def dna(n, gc=0.5):
    return "".join(random.choices("GC", k=1)[0] if random.random() < gc else random.choices("AT", k=1)[0] for _ in range(n))
def wrap(s, w=60): return "\n".join(s[i:i+w] for i in range(0, len(s), w))
MOTIF = "ATGGCGTACGTTAGC"
RC = MOTIF.translate(str.maketrans("ACGT", "TGCA"))[::-1]

def fasta(*seqs): return "".join(f">seq{i}\n{wrap(s)}\n" for i, s in enumerate(seqs))
base = dna(600)
FILES = {
 "good.fasta":            (fasta(base), "VALID"),
 "many_n.fasta":          (fasta(dna(300) + "N"*100 + dna(200)), "FAILED_QC"),
 "fragmented.fasta":      (fasta(*[dna(80) for _ in range(150)]), "FAILED_QC"),
 "low_gc.fasta":          (fasta(dna(600, gc=0.05)), "FAILED_QC"),
 "protein.fasta":         (">p\nMKVLAAGIVGLLLAQPSTEWRHYFDKNCQ\nMKVLAAGIVGLLLAQPSTEWRHYFDKNCQ\n", "INVALID"),
 "empty.fasta":           ("", "INVALID"),
 "no_header.fasta":       (wrap(dna(300)) + "\n", "INVALID"),
 "primer_fwd.fasta":      (fasta(dna(200) + MOTIF + dna(200)), "FLAGGED_POSITIVE"),
 "primer_rev.fasta":      (fasta(dna(200) + RC + dna(200)), "FLAGGED_POSITIVE"),
 # motif forced across a 60-col line break:
 "primer_split.fasta":    (">s\n" + dna(50) + MOTIF[:8] + "\n" + MOTIF[8:] + dna(100) + "\n", "FLAGGED_POSITIVE"),
 # motif in a file that fails QC must NOT be reported (gate halts first):
 "primer_but_bad.fasta":  (fasta(dna(200) + MOTIF + "N"*150), "FAILED_QC"),
 "lower_case.fasta":      (fasta(base.lower()), "VALID"),
}

with mock_aws():
    s3 = boto3.client("s3"); sns = boto3.client("sns"); sqs = boto3.client("sqs")
    s3.create_bucket(Bucket="test-bucket", CreateBucketConfiguration={"LocationConstraint": "eu-north-1"})
    t = boto3.resource("dynamodb").create_table(TableName="BioFastCheckResults",
        KeySchema=[{"AttributeName":"FileID","KeyType":"HASH"}],
        AttributeDefinitions=[{"AttributeName":"FileID","AttributeType":"S"}], BillingMode="PAY_PER_REQUEST")
    topic = sns.create_topic(Name="t")["TopicArn"]
    q = sqs.create_queue(QueueName="q")["QueueUrl"]
    qarn = sqs.get_queue_attributes(QueueUrl=q, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=qarn)
    os.environ["SNS_TOPIC_ARN"] = topic
    os.environ["PRIMER_MOTIFS"] = f"DEMO:{MOTIF}"
    sys.path.insert(0, os.path.dirname(__file__) or ".")
    import processor_v2 as p

    def event(key, etag="e1"):
        return {"Records":[{"eventName":"ObjectCreated:Put","s3":{"bucket":{"name":"test-bucket"},"object":{"key":key.replace(" ","+"),"eTag":etag}}}]}

    ok = True
    for name, (body, expected) in FILES.items():
        s3.put_object(Bucket="test-bucket", Key=f"web-uploads/{name}", Body=body.encode())
        r = p.lambda_handler(event(f"web-uploads/{name}"), None)["processed"][0]
        good = r["status"] == expected; ok &= good
        print(f"{'PASS' if good else 'FAIL'}  {name:22} expected {expected:17} got {r['status']:17} {r['flags']}")

    # idempotency: same S3 event delivered twice -> 1 row, 1 email
    before_rows = t.scan()["Count"]
    n_msgs_before = len(sqs.receive_message(QueueUrl=q, MaxNumberOfMessages=10, WaitTimeSeconds=0).get("Messages", []))
    p.lambda_handler(event("web-uploads/good.fasta"), None)
    dup_ok = t.scan()["Count"] == before_rows
    print(f"{'PASS' if dup_ok else 'FAIL'}  duplicate S3 event creates no extra row"); ok &= dup_ok

    # key with spaces/URL-encoding
    s3.put_object(Bucket="test-bucket", Key="web-uploads/my file.fasta", Body=FILES["good.fasta"][0].encode())
    r = p.lambda_handler(event("web-uploads/my file.fasta", "e9"), None)["processed"][0]
    print(f"{'PASS' if r['status']=='VALID' else 'FAIL'}  URL-encoded key (space) handled"); ok &= r["status"]=="VALID"

    # inspect a stored record + an email
    item = [i for i in t.scan()["Items"] if "primer_but_bad" in i["SourceFile"]][0]
    print("\nprimer_but_bad record -> Primer_Hits:", dict(item["Primer_Hits"]), "| Downstream_Ready:", item["Downstream_Ready"])
    item = [i for i in t.scan()["Items"] if "primer_fwd" in i["SourceFile"]][0]
    subj, body = p.build_email(item); print("\nSample email:\nSubject:", subj, "\n" + body)
    print("\nALL TESTS PASSED" if ok else "\nSOME TESTS FAILED"); sys.exit(0 if ok else 1)
