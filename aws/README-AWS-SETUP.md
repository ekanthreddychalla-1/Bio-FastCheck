# AWS setup quick reference

## 1. Web API Lambda
Function: `BioFastCheckWebAPI` (Python 3.12)
Environment variables:
- `BUCKET_NAME=biofastcheck-raw-data`
- `TABLE_NAME=BioFastCheckResults`
- `ALLOWED_ORIGIN=http://localhost:5173`

Paste `api_lambda.py` into the Lambda editor and Deploy.

## 2. IAM permissions
Attach `iam-policy-web-api.json` to the new web API Lambda execution role. Do not attach it to the existing processor role unless you have a specific reason. This role needs `s3:PutObject` for the bucket and `dynamodb:Scan` for the results table.

## 3. S3 CORS
S3 Console -> bucket `biofastcheck-raw-data` -> Permissions -> Cross-origin resource sharing (CORS) -> Edit. Paste `s3-bucket-cors.json`.
If the bucket already has CORS rules, merge these rules rather than deleting rules you still need.

## 4. API Gateway HTTP API
Create HTTP API, integrate `BioFastCheckWebAPI`, create routes `POST /upload-url` and `GET /results`, enable CORS for `http://localhost:5173`, methods GET/POST/OPTIONS, header content-type. Use `$default` auto-deploy stage if available.

## 5. Region and account
The included IAM policy uses the account ID and region from the project context. Confirm the account ID is yours before attaching it. Region should be `eu-north-1`.
