import json
import os
import re
from decimal import Decimal
import boto3
from botocore.config import Config
from boto3.dynamodb.conditions import Attr

s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
dynamodb = boto3.resource("dynamodb")

BUCKET_NAME = os.environ.get("BUCKET_NAME", "biofastcheck-raw-data")
TABLE_NAME = os.environ.get("TABLE_NAME", "BioFastCheckResults")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "http://localhost:5173")
table = dynamodb.Table(TABLE_NAME)

def _json_default(value):
    # DynamoDB returns numbers as Decimal; send real numbers to the browser.
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return str(value)

def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Headers": "content-type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Vary": "Origin"
        },
        "body": json.dumps(body, default=_json_default)
    }

def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "/")

    if method == "OPTIONS":
        return response(200, {"ok": True})

    try:
        if method == "POST" and path.endswith("/upload-url"):
            body = json.loads(event.get("body") or "{}")
            filename = os.path.basename(body.get("fileName", ""))
            if not filename or not re.search(r"\.(fasta|fa|fna)$", filename, re.IGNORECASE):
                return response(400, {"message": "Use a .fasta, .fa, or .fna filename."})
            # Restrict key characters and avoid overwriting previous test uploads.
            safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
            key = f"web-uploads/{context.aws_request_id}-{safe_name}"
            upload_url = s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": BUCKET_NAME, "Key": key, "ContentType": "text/plain"},
                ExpiresIn=300
            )
            return response(200, {"uploadUrl": upload_url, "key": key, "expiresIn": 300})

        if method == "GET" and path.endswith("/results"):
            # Read the whole table (capped) so the NEWEST records are never missed,
            # then sort by timestamp. Fine for a demo-sized table.
            items, kwargs = [], {}
            while True:
                page = table.scan(**kwargs)
                items.extend(page.get("Items", []))
                if "LastEvaluatedKey" not in page or len(items) >= 2000:
                    break
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
            items.sort(key=lambda item: str(item.get("Timestamp", "")), reverse=True)
            return response(200, {"items": items[:50]})

        return response(404, {"message": f"No route for {method} {path}"})
    except Exception as exc:
        print(f"Request failed: {type(exc).__name__}: {exc}")
        return response(500, {"message": "Request failed. Check the BioFastCheckWebAPI CloudWatch logs."})
