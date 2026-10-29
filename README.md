# Bio-FastCheck Reactive Web App (AWS)

A React + Vite dashboard for your existing Bio-FastCheck AWS pipeline.

## What it does
- Uploads a `.fasta` / `.fa` file to your S3 bucket using a short-lived presigned URL.
- Your existing S3 `ObjectCreated` trigger invokes `BioFastCheckProcessor`.
- The processor stores analysis results in DynamoDB and sends the SNS email you already verified.
- The dashboard can query recent results through a small API Lambda + API Gateway.

**Important:** The browser never receives AWS access keys. Do not put AWS credentials in `.env` or frontend code.

## Architecture

React browser -> API Gateway HTTP API -> `BioFastCheckWebAPI` Lambda
- `POST /upload-url`: returns a short-lived S3 presigned PUT URL
- `GET /results`: returns recent DynamoDB records

Browser -> presigned S3 URL -> `biofastcheck-raw-data`
S3 event -> existing `BioFastCheckProcessor` -> DynamoDB + SNS email

## Processor (quality gate + primer scan)
The S3-triggered processor lives in `aws/processor-v2/processor_v2.py` (paste it into the `BioFastCheckProcessor` Lambda, handler `lambda_function.lambda_handler`).
It writes statuses `VALID`, `FAILED_QC`, `FLAGGED_POSITIVE`, `INVALID`. Set the target primer with the Lambda env var `PRIMER_MOTIFS` (`NAME:SEQUENCE`, 10-15 bp). Local tests: `pip install moto boto3 && python aws/processor-v2/test_processor_v2.py`.
The S3 trigger must exist for **each** suffix you accept (`.fasta`, `.fa`, `.fna`), otherwise those uploads are silently ignored.

## Prerequisites
- AWS region: `eu-north-1` (Europe Stockholm)
- Existing S3 bucket: `biofastcheck-raw-data`
- Existing DynamoDB table: `BioFastCheckResults`
- Existing processor Lambda: `BioFastCheckProcessor`
- Node.js 20+ and npm
- AWS Console access

## Part A — Create the API Lambda

1. AWS Console -> Lambda -> Create function.
2. Choose **Author from scratch**.
3. Function name: `BioFastCheckWebAPI`
4. Runtime: Python 3.12
5. Create/select an execution role. Then open Configuration -> Permissions -> role link.
6. In IAM, attach permissions with the policy below (replace account ID only if yours differs).
7. In Lambda -> Configuration -> Environment variables, add:
   - `BUCKET_NAME` = `biofastcheck-raw-data`
   - `TABLE_NAME` = `BioFastCheckResults`
   - `ALLOWED_ORIGIN` = `http://localhost:5173`
8. Open Code, replace the starter code with `aws/api_lambda.py` contents, then Deploy.

### IAM policy for BioFastCheckWebAPI

Attach this inline policy to the **new web API Lambda role** (not your existing processor role). It permits presigned uploads to the named bucket and reads from your results table.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PresignFastaUploads",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::biofastcheck-raw-data/*"
    },
    {
      "Sid": "ReadBioFastCheckResults",
      "Effect": "Allow",
      "Action": ["dynamodb:Scan"],
      "Resource": "arn:aws:dynamodb:eu-north-1:477213278851:table/BioFastCheckResults"
    }
  ]
}
```

For a classroom/demo project this simple Scan endpoint is convenient. For production, use pagination, authentication/authorization, stricter upload limits, and a queryable index rather than unrestricted table scans.

## Part B — Create API Gateway

1. AWS Console -> API Gateway -> Create API -> **HTTP API** -> Build.
2. Add integration -> Lambda -> select `BioFastCheckWebAPI` in `eu-north-1`.
3. Configure routes:
   - `POST /upload-url`
   - `GET /results`
4. Enable CORS:
   - Allowed origin: `http://localhost:5173`
   - Allowed methods: `GET`, `POST`, `OPTIONS`
   - Allowed headers: `content-type`
5. Create a stage named `$default` with auto-deploy enabled.
6. Copy the **Invoke URL** (format like `https://abc123.execute-api.eu-north-1.amazonaws.com`).
7. Update `ALLOWED_ORIGIN` on the API Lambda to your actual frontend origin. For local testing, use `http://localhost:5173`.

If you use a named stage instead of `$default`, include the stage path in the API base URL as shown in the API Gateway console.

## Part C — Configure the React app

1. Extract this ZIP.
2. Open a terminal in the extracted `Bio-FastCheck-main` folder.
3. Run:

```bash
npm install
```

4. Copy `.env.example` to `.env`.
5. Set `VITE_API_BASE_URL` to your API Gateway invoke URL. Do not add a trailing slash.

Example:
```env
VITE_API_BASE_URL=https://abc123.execute-api.eu-north-1.amazonaws.com
```

6. Start the site:

```bash
npm run dev
```

7. Open the local URL Vite prints, usually `http://localhost:5173`.

## Part D — Test the full workflow

1. In the dashboard, upload a small `.fasta` file.
2. Wait about 5–15 seconds.
3. Click **Refresh results**.
4. Confirm a new result appears with file name, sequence length, GC content, status and timestamp.
5. Check your email for the SNS analysis report.

Use a **new filename** for each test upload so the S3 object-created event fires again. The existing S3 trigger suffix `.fasta` should match.

## Troubleshooting
- **CORS error:** Check API Gateway CORS allowed origin and redeploy; verify `ALLOWED_ORIGIN`.
- **403 on upload:** Check the web API Lambda role has `s3:PutObject` for the bucket; confirm the bucket name and region.
- **Upload succeeds but no result:** Check the existing `BioFastCheckProcessor` Lambda logs and its S3 trigger. Use a new `.fasta` key.
- **Results API returns 500:** Check the web API Lambda role has `dynamodb:Scan` on the correct table.
- **No email:** Check the existing processor's `SNS_TOPIC_ARN`, SNS subscription confirmation, and `sns:Publish` permission.
- **Do not upload real patient/genomic data** to a demo account without appropriate security, privacy, access controls and approval.

## Notes
- The results endpoint returns the most recent 50 items from a DynamoDB Scan. DynamoDB Scan ordering is not chronological; the app sorts the returned items by timestamp.
- This is a demo scaffold, not a production-secured service.
