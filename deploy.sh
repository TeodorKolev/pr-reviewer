#!/bin/bash
set -e

PROJECT="pr-reviewer-501116"
SERVICE="pr-reviewer"
REGION="us-east1"

echo "🚀 Deploying $SERVICE..."
agents-cli deploy --project "$PROJECT"

echo "🔓 Restoring public access..."
gcloud run services add-iam-policy-binding "$SERVICE" \
  --region="$REGION" \
  --member="allUsers" \
  --role="roles/run.invoker" \
  --project="$PROJECT"

echo "🔑 Restoring secrets..."
gcloud run services update "$SERVICE" \
  --region="$REGION" \
  --project="$PROJECT" \
  --set-secrets="GOOGLE_API_KEY=GOOGLE_API_KEY:latest,GITHUB_TOKEN=GITHUB_TOKEN:latest" \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=False,GITHUB_MCP_MODE=binary"

echo "✅ Done."
gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format="value(status.url)"
