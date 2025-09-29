#!/bin/bash

# Facto AI Deployment Script for facto-ai.facto.com.au

set -e

echo "🚀 Deploying Facto AI Test Case Generator to Google Cloud Run..."

# Configuration
PROJECT_ID="facto-ai-project"  
SERVICE_NAME="facto-ai-testcase-generator"
REGION="asia-southeast1"  
DOMAIN="facto-ai.facto.com.au"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Check if gcloud is installed and authenticated
if ! command -v gcloud &> /dev/null; then
    echo "❌ Google Cloud CLI not found. Please install it first."
    echo "Visit: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Set the project
echo "📋 Setting GCP project to ${PROJECT_ID}..."
gcloud config set project ${PROJECT_ID}

# Enable required APIs
echo "🔧 Enabling required GCP APIs..."
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable firestore.googleapis.com

# Initialize Firestore if not already done
echo "🗄️ Setting up Firestore database..."
if ! gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
    echo "Creating Firestore database in multi-region..."
    gcloud firestore databases create --location=nam5 --type=firestore-native
    echo "✅ Firestore database created"
else
    echo "✅ Firestore database already exists"
fi

# Create secret in Secret Manager
echo "🔐 Setting up OpenAI API key in Secret Manager..."
if ! gcloud secrets describe openai-api-key >/dev/null 2>&1; then
    read -p "Enter your OpenAI API key: " -s OPENAI_API_KEY
    echo
    echo "${OPENAI_API_KEY}" | gcloud secrets create openai-api-key --data-file=-
    echo "✅ Secret created successfully"
else
    echo "✅ Secret already exists"
fi

# Build and deploy to Cloud Run
echo "🏗️ Building and deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
    --source . \
    --platform managed \
    --region ${REGION} \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 1 \
    --timeout 300 \
    --concurrency 10 \
    --min-instances 0 \
    --max-instances 10 \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
    --quiet

# Get the service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format='value(status.url)')

echo "✅ Deployment complete!"
echo "🌐 Your app is available at: ${SERVICE_URL}"

# Set up custom domain mapping
echo ""
echo "🌐 Setting up custom domain mapping for ${DOMAIN}..."
gcloud run domain-mappings create \
    --service ${SERVICE_NAME} \
    --domain ${DOMAIN} \
    --region ${REGION}

echo ""
echo "✅ Domain mapping created successfully!"
echo ""
echo "🔧 CLOUDFLARE DNS CONFIGURATION REQUIRED:"
echo "=============================================="
echo "1. Login to your Cloudflare dashboard"
echo "2. Select the facto.com.au domain"
echo "3. Go to DNS → Records"
echo "4. Add the following CNAME record:"
echo ""
echo "   Type: CNAME"
echo "   Name: facto-ai"
echo "   Content: ghs.googlehosted.com"
echo "   Proxy status: DNS only (gray cloud icon)"
echo "   TTL: Auto"
echo ""
echo "⚠️  IMPORTANT: Set Proxy status to 'DNS only' (gray cloud)"
echo "   This allows Google to manage the SSL certificate"
echo ""
echo "=============================================="
echo ""

# Wait for user confirmation
read -p "Press Enter after you've added the DNS record in Cloudflare..."

echo "🔍 Checking domain mapping status..."
sleep 10

# Check domain status
gcloud run domain-mappings describe ${DOMAIN} --region=${REGION} --format="table(metadata.name,status.conditions[0].type,status.conditions[0].status,status.conditions[0].reason)"

echo ""
echo "⏰ SSL certificate provisioning may take 15-60 minutes"
echo "🔍 Check status with: gcloud run domain-mappings describe ${DOMAIN} --region=${REGION}"
echo ""
echo "🎉 Once DNS propagates, your app will be available at:"
echo "   https://${DOMAIN}"
echo ""
echo "📊 Monitor your service at:"
echo "   https://console.cloud.google.com/run/detail/${REGION}/${SERVICE_NAME}"