#!/usr/bin/env bash
# =============================================================================
# PEA — Azure Container Apps Deployment
# =============================================================================
# Creates the Container Apps environment, pipeline Job, and dashboard App.
#
# Run AFTER:
#   1. infra/setup.sh   (creates ACR + storage)
#   2. GitHub CI push   (builds + pushes images to ACR)
#
# Usage:
#   chmod +x infra/deploy.sh
#   ./infra/deploy.sh
#
# To update a running deployment after a code change (new image pushed):
#   az containerapp job update --name pea-pipeline-job --resource-group pea-rg \
#       --image <ACR_LOGIN_SERVER>/pea-pipeline:latest
#   az containerapp update --name pea-dashboard --resource-group pea-rg \
#       --image <ACR_LOGIN_SERVER>/pea-dashboard:latest
# =============================================================================

set -euo pipefail

# ── Configuration — fill these in from setup.sh output ───────────────────────

RESOURCE_GROUP="pea-rg"
LOCATION="eastus"
ACR_LOGIN_SERVER=""          # e.g. pearegistry12345.azurecr.io
ACR_USERNAME=""
ACR_PASSWORD=""
BLOB_CONTAINER="pea-outputs"
BLOB_PREFIX="runs"

# Pipeline secrets — read from environment or fill directly
AZURE_FOUNDRY_API_KEY="${AZURE_FOUNDRY_API_KEY:-}"
AZURE_OPENAI_ENDPOINT="${AZURE_OPENAI_ENDPOINT:-}"
AZURE_STORAGE_CONN_STR="${AZURE_STORAGE_CONNECTION_STRING:-}"
BBC_USER="${BBC_MONITORING_USER_NAME:-}"
BBC_PASS="${BBC_MONITORING_USER_PASSWORD:-}"
ANTHROPIC_KEY="${ANTHROPIC_API_KEY:-}"

SUBSCRIPTION_ID=$(az account show --query id -o tsv)

CONTAINER_APPS_ENV="pea-env"
PIPELINE_JOB_NAME="pea-pipeline-job"
DASHBOARD_APP_NAME="pea-dashboard"

# ── Colours ───────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}  $*"; }

# ── Validate required vars ────────────────────────────────────────────────────

if [[ -z "$ACR_LOGIN_SERVER" || -z "$ACR_USERNAME" || -z "$ACR_PASSWORD" ]]; then
    echo "ERROR: ACR_LOGIN_SERVER, ACR_USERNAME, and ACR_PASSWORD must be set in this script."
    echo "       Run infra/setup.sh first and copy the values here."
    exit 1
fi

if [[ -z "$AZURE_STORAGE_CONN_STR" ]]; then
    warn "AZURE_STORAGE_CONNECTION_STRING is not set — pipeline uploads will be disabled"
fi

# ── 1. Container Apps Environment ────────────────────────────────────────────

log "Creating Container Apps environment: $CONTAINER_APPS_ENV"
az containerapp env create \
    --name "$CONTAINER_APPS_ENV" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none

# ── 2. Pipeline Job ───────────────────────────────────────────────────────────

log "Creating pipeline job: $PIPELINE_JOB_NAME"

# Build secrets list (only include non-empty secrets)
SECRETS_ARGS=()
ENV_VARS_ARGS=()

if [[ -n "$AZURE_STORAGE_CONN_STR" ]]; then
    SECRETS_ARGS+=("storage-conn-str=$AZURE_STORAGE_CONN_STR")
    ENV_VARS_ARGS+=("AZURE_STORAGE_CONNECTION_STRING=secretref:storage-conn-str")
fi
if [[ -n "$AZURE_FOUNDRY_API_KEY" ]]; then
    SECRETS_ARGS+=("azure-foundry-key=$AZURE_FOUNDRY_API_KEY")
    ENV_VARS_ARGS+=("AZURE_FOUNDRY_API_KEY=secretref:azure-foundry-key")
fi
if [[ -n "$AZURE_OPENAI_ENDPOINT" ]]; then
    SECRETS_ARGS+=("azure-endpoint=$AZURE_OPENAI_ENDPOINT")
    ENV_VARS_ARGS+=("AZURE_OPENAI_ENDPOINT=secretref:azure-endpoint")
fi
if [[ -n "$BBC_USER" ]]; then
    SECRETS_ARGS+=("bbc-username=$BBC_USER")
    ENV_VARS_ARGS+=("BBC_MONITORING_USER_NAME=secretref:bbc-username")
fi
if [[ -n "$BBC_PASS" ]]; then
    SECRETS_ARGS+=("bbc-password=$BBC_PASS")
    ENV_VARS_ARGS+=("BBC_MONITORING_USER_PASSWORD=secretref:bbc-password")
fi
if [[ -n "$ANTHROPIC_KEY" ]]; then
    SECRETS_ARGS+=("anthropic-key=$ANTHROPIC_KEY")
    ENV_VARS_ARGS+=("ANTHROPIC_API_KEY=secretref:anthropic-key")
fi

az containerapp job create \
    --name "$PIPELINE_JOB_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$CONTAINER_APPS_ENV" \
    --trigger-type Manual \
    --replica-timeout 7200 \
    --replica-retry-limit 1 \
    --replica-completion-count 1 \
    --parallelism 1 \
    --image "$ACR_LOGIN_SERVER/pea-pipeline:latest" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_USERNAME" \
    --registry-password "$ACR_PASSWORD" \
    --cpu 2.0 \
    --memory "4Gi" \
    ${#SECRETS_ARGS[@]:+--secrets "$(IFS=' '; echo "${SECRETS_ARGS[*]}")"} \
    ${#ENV_VARS_ARGS[@]:+--env-vars "$(IFS=' '; echo "${ENV_VARS_ARGS[*]}")"} \
    --output none

log "Pipeline job created: $PIPELINE_JOB_NAME"

# ── 3. Dashboard App ──────────────────────────────────────────────────────────

log "Creating dashboard app: $DASHBOARD_APP_NAME"

DASHBOARD_SECRETS=()
DASHBOARD_ENV=()

if [[ -n "$AZURE_STORAGE_CONN_STR" ]]; then
    DASHBOARD_SECRETS+=("storage-conn-str=$AZURE_STORAGE_CONN_STR")
    DASHBOARD_ENV+=("AZURE_STORAGE_CONNECTION_STRING=secretref:storage-conn-str")
fi

DASHBOARD_ENV+=(
    "AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION_ID"
    "AZURE_RESOURCE_GROUP=$RESOURCE_GROUP"
    "CONTAINER_APPS_JOB_NAME=$PIPELINE_JOB_NAME"
    "BLOB_CONTAINER_NAME=$BLOB_CONTAINER"
    "BLOB_PREFIX=$BLOB_PREFIX"
)

az containerapp create \
    --name "$DASHBOARD_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$CONTAINER_APPS_ENV" \
    --image "$ACR_LOGIN_SERVER/pea-dashboard:latest" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_USERNAME" \
    --registry-password "$ACR_PASSWORD" \
    --ingress external \
    --target-port 8501 \
    --cpu 0.5 \
    --memory "1Gi" \
    --min-replicas 1 \
    --max-replicas 2 \
    ${#DASHBOARD_SECRETS[@]:+--secrets "$(IFS=' '; echo "${DASHBOARD_SECRETS[*]}")"} \
    --env-vars "$(IFS=' '; echo "${DASHBOARD_ENV[*]}")" \
    --output none

# ── 4. Assign Managed Identity for job triggering ─────────────────────────────

log "Enabling system-assigned managed identity on dashboard app"
az containerapp identity assign \
    --name "$DASHBOARD_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --system-assigned \
    --output none

DASHBOARD_PRINCIPAL_ID=$(az containerapp show \
    --name "$DASHBOARD_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "identity.principalId" -o tsv)

log "Granting Contributor role on job resource group to dashboard identity"
az role assignment create \
    --assignee "$DASHBOARD_PRINCIPAL_ID" \
    --role "Contributor" \
    --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP" \
    --output none

# ── 5. Summary ────────────────────────────────────────────────────────────────

DASHBOARD_URL=$(az containerapp show \
    --name "$DASHBOARD_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.configuration.ingress.fqdn" -o tsv)

echo ""
echo "============================================================"
echo "  DEPLOYMENT COMPLETE"
echo "============================================================"
echo ""
echo "  Pipeline job:  $PIPELINE_JOB_NAME"
echo "  Dashboard URL: https://$DASHBOARD_URL"
echo ""
echo "--- Trigger a run manually (CLI) ---------------------------"
echo "  az containerapp job start \\"
echo "    --name $PIPELINE_JOB_NAME \\"
echo "    --resource-group $RESOURCE_GROUP \\"
echo "    --args \"--provider azure --countries ZA,NG --days 14 \\"
echo "            --source both --stage acquire \\"
echo "            --upload-to az://${BLOB_CONTAINER}/${BLOB_PREFIX}\""
echo ""
echo "--- Monitor job executions ----------------------------------"
echo "  az containerapp job execution list \\"
echo "    --name $PIPELINE_JOB_NAME \\"
echo "    --resource-group $RESOURCE_GROUP \\"
echo "    --output table"
echo "============================================================"
echo ""
