#!/usr/bin/env bash
# =============================================================================
# PEA — Azure Infrastructure Setup
# =============================================================================
# Creates all Azure resources needed to run the pipeline in the cloud.
#
# Prerequisites:
#   - Azure CLI installed: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli
#   - Logged in: az login
#   - Target subscription selected: az account set --subscription <id>
#
# Usage:
#   chmod +x infra/setup.sh
#   ./infra/setup.sh
#
# After this script completes:
#   1. Copy the printed values into your GitHub repo secrets (Settings → Secrets)
#   2. Push to main to trigger the Docker build + push CI workflow
#   3. Run infra/deploy.sh to create the Container Apps resources
# =============================================================================

set -euo pipefail

# ── Configuration — edit these before running ─────────────────────────────────

RESOURCE_GROUP="pea-rg"
LOCATION="eastus"                     # az account list-locations -o table
ACR_NAME="pearegistry${RANDOM}"       # must be globally unique; auto-randomised
STORAGE_ACCOUNT="peastorage${RANDOM}" # must be globally unique; auto-randomised
BLOB_CONTAINER="pea-outputs"

# ── Colours for output ────────────────────────────────────────────────────────

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}  $*"; }

# ── 1. Resource Group ─────────────────────────────────────────────────────────

log "Creating resource group: $RESOURCE_GROUP ($LOCATION)"
az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none

# ── 2. Azure Container Registry ───────────────────────────────────────────────

log "Creating ACR: $ACR_NAME"
az acr create \
    --name "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --sku Basic \
    --admin-enabled true \
    --output none

ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)
ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)

log "ACR ready: $ACR_LOGIN_SERVER"

# ── 3. Storage Account + Blob Container ───────────────────────────────────────

log "Creating storage account: $STORAGE_ACCOUNT"
az storage account create \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku Standard_LRS \
    --kind StorageV2 \
    --output none

STORAGE_CONN_STR=$(az storage account show-connection-string \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    -o tsv)

log "Creating blob container: $BLOB_CONTAINER"
az storage container create \
    --name "$BLOB_CONTAINER" \
    --connection-string "$STORAGE_CONN_STR" \
    --output none

log "Storage ready: $STORAGE_ACCOUNT / $BLOB_CONTAINER"

# ── 4. Summary: values needed for next steps ──────────────────────────────────

SUBSCRIPTION_ID=$(az account show --query id -o tsv)

echo ""
echo "============================================================"
echo "  SETUP COMPLETE — save these values"
echo "============================================================"
echo ""
echo "--- GitHub Secrets (Settings → Secrets → Actions) ----------"
echo "  ACR_LOGIN_SERVER = $ACR_LOGIN_SERVER"
echo "  ACR_USERNAME     = $ACR_USERNAME"
echo "  ACR_PASSWORD     = $ACR_PASSWORD"
echo ""
echo "--- .env file additions ------------------------------------"
echo "  AZURE_STORAGE_CONNECTION_STRING=$STORAGE_CONN_STR"
echo ""
echo "--- infra/deploy.sh variables (pre-filled) -----------------"
echo "  RESOURCE_GROUP=$RESOURCE_GROUP"
echo "  ACR_LOGIN_SERVER=$ACR_LOGIN_SERVER"
echo "  ACR_USERNAME=$ACR_USERNAME"
echo "  ACR_PASSWORD=$ACR_PASSWORD"
echo "  STORAGE_ACCOUNT=$STORAGE_ACCOUNT"
echo "  BLOB_CONTAINER=$BLOB_CONTAINER"
echo "  SUBSCRIPTION_ID=$SUBSCRIPTION_ID"
echo ""
echo "--- Next steps ---------------------------------------------"
echo "  1. Add the GitHub Secrets above to your repository"
echo "  2. Push to main  →  GitHub Actions builds + pushes images to ACR"
echo "  3. Run: ./infra/deploy.sh  →  creates Container Apps Job + Dashboard"
echo "============================================================"
echo ""
