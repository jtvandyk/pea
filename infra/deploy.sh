#!/usr/bin/env bash
# Deploy PEA pipeline to Azure Container Apps Jobs.
#
# Prerequisites:
#   az login (or az login --service-principal ...)
#   az extension add --name containerapp
#
# Required env vars (or edit the variables below):
#   AZURE_FOUNDRY_API_KEY   — Azure AI Foundry key, stored in Key Vault
#   ALERT_EMAIL             — email for job-failure alerts
#
# Usage:
#   bash infra/deploy.sh
#
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────
RESOURCE_GROUP="${RESOURCE_GROUP:-pea-rg}"
LOCATION="${LOCATION:-eastus}"

# Fill these in from the output of infra/setup.sh:
ACR_NAME="${ACR_NAME:?Set ACR_NAME to your Azure Container Registry name}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:?Set STORAGE_ACCOUNT to your storage account name}"
ADLS_FILESYSTEM="${ADLS_FILESYSTEM:-pea-data}"

KV_NAME="${KV_NAME:-pea-kv}"
IDENTITY_NAME="${IDENTITY_NAME:-pea-identity}"
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-pea-env}"
LOG_WORKSPACE="${LOG_WORKSPACE:-pea-logs}"
ALERT_EMAIL="${ALERT_EMAIL:?Set ALERT_EMAIL to receive job-failure notifications}"
IMAGE="${IMAGE:-$ACR_NAME.azurecr.io/pea-pipeline:latest}"

STORAGE_URL="https://$STORAGE_ACCOUNT.dfs.core.windows.net"

echo "=== PEA Azure Container Apps deployment ==="
echo "Resource group : $RESOURCE_GROUP"
echo "Location       : $LOCATION"
echo "ACR            : $ACR_NAME"
echo "Storage (ADLS) : $STORAGE_ACCOUNT / $ADLS_FILESYSTEM"
echo "Image          : $IMAGE"
echo ""

# ── 1. Log Analytics workspace ─────────────────────────────────────────────────
echo "--- Creating Log Analytics workspace: $LOG_WORKSPACE ---"
az monitor log-analytics workspace create \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$LOG_WORKSPACE" \
  --location "$LOCATION" \
  --output none

LOG_WORKSPACE_ID=$(az monitor log-analytics workspace show \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$LOG_WORKSPACE" \
  --query customerId --output tsv)

LOG_WORKSPACE_KEY=$(az monitor log-analytics workspace get-shared-keys \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$LOG_WORKSPACE" \
  --query primarySharedKey --output tsv)

# ── 2. Container Apps Environment ─────────────────────────────────────────────
echo "--- Creating Container Apps Environment: $ENVIRONMENT_NAME ---"
az containerapp env create \
  --name "$ENVIRONMENT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --logs-workspace-id "$LOG_WORKSPACE_ID" \
  --logs-workspace-key "$LOG_WORKSPACE_KEY" \
  --output none

# ── 3. Key Vault ───────────────────────────────────────────────────────────────
echo "--- Creating Key Vault: $KV_NAME ---"
az keyvault create \
  --name "$KV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --enable-rbac-authorization true \
  --output none

KV_ID=$(az keyvault show --name "$KV_NAME" --resource-group "$RESOURCE_GROUP" \
  --query id --output tsv)
KV_URI=$(az keyvault show --name "$KV_NAME" --resource-group "$RESOURCE_GROUP" \
  --query properties.vaultUri --output tsv)
KV_URI="${KV_URI%/}"  # strip trailing slash if present

echo "  Storing secrets in Key Vault..."
az keyvault secret set \
  --vault-name "$KV_NAME" \
  --name pea-foundry-api-key \
  --value "${AZURE_FOUNDRY_API_KEY:?Set AZURE_FOUNDRY_API_KEY env var}" \
  --output none

if [[ -n "${BBC_MONITORING_USER_NAME:-}" ]]; then
  az keyvault secret set --vault-name "$KV_NAME" \
    --name pea-bbc-username --value "$BBC_MONITORING_USER_NAME" --output none
fi
if [[ -n "${BBC_MONITORING_USER_PASSWORD:-}" ]]; then
  az keyvault secret set --vault-name "$KV_NAME" \
    --name pea-bbc-password --value "$BBC_MONITORING_USER_PASSWORD" --output none
fi

# ── 4. User-assigned managed identity ─────────────────────────────────────────
echo "--- Creating managed identity: $IDENTITY_NAME ---"
az identity create \
  --name "$IDENTITY_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

IDENTITY_ID=$(az identity show --name "$IDENTITY_NAME" \
  --resource-group "$RESOURCE_GROUP" --query id --output tsv)
PRINCIPAL_ID=$(az identity show --name "$IDENTITY_NAME" \
  --resource-group "$RESOURCE_GROUP" --query principalId --output tsv)

# Role assignments sometimes need a brief propagation delay after identity creation
echo "  Waiting for identity propagation..."
sleep 15

# ── 5. Role assignments ────────────────────────────────────────────────────────
echo "--- Assigning roles ---"

ACR_ID=$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" \
  --query id --output tsv)
STORAGE_ID=$(az storage account show --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" --query id --output tsv)

az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role AcrPull --scope "$ACR_ID" --output none

az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID" --output none

az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope "$STORAGE_ID" --output none

# ── 6. pea-daily Container Apps Job (cron) ────────────────────────────────────
echo "--- Creating Container Apps Job: pea-daily ---"
az containerapp job create \
  --name pea-daily \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENVIRONMENT_NAME" \
  --trigger-type Schedule \
  --cron-expression "0 6 * * *" \
  --replica-timeout 14400 \
  --replica-retry-limit 2 \
  --replica-completion-count 1 \
  --parallelism 1 \
  --image "$IMAGE" \
  --registry-server "$ACR_NAME.azurecr.io" \
  --registry-identity "$IDENTITY_ID" \
  --user-assigned-identities "$IDENTITY_ID" \
  --cpu 2 --memory 4Gi \
  --env-vars \
    "AZURE_STORAGE_ACCOUNT_URL=$STORAGE_URL" \
    "AZURE_OPENAI_ENDPOINT=secretref:pea-openai-endpoint" \
    "AZURE_FOUNDRY_API_KEY=secretref:pea-foundry-api-key" \
  --secrets \
    "pea-foundry-api-key=keyvaultref:${KV_URI}/secrets/pea-foundry-api-key,identityref:$IDENTITY_ID" \
  --args \
    "--stage" "all" \
    "--countries" "NG,ZA,UG,DZ" \
    "--days" "2" \
    "--resume" \
    "--upload-to" "abfss://$ADLS_FILESYSTEM/runs" \
    "--workers" "4" \
    "--rpm-limit" "450" \
  --output none

# ── 7. pea-backfill Container Apps Job (manual trigger) ───────────────────────
echo "--- Creating Container Apps Job: pea-backfill ---"
az containerapp job create \
  --name pea-backfill \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENVIRONMENT_NAME" \
  --trigger-type Manual \
  --replica-timeout 86400 \
  --replica-retry-limit 1 \
  --replica-completion-count 1 \
  --parallelism 1 \
  --image "$IMAGE" \
  --registry-server "$ACR_NAME.azurecr.io" \
  --registry-identity "$IDENTITY_ID" \
  --user-assigned-identities "$IDENTITY_ID" \
  --cpu 4 --memory 8Gi \
  --env-vars \
    "AZURE_STORAGE_ACCOUNT_URL=$STORAGE_URL" \
    "AZURE_OPENAI_ENDPOINT=secretref:pea-openai-endpoint" \
    "AZURE_FOUNDRY_API_KEY=secretref:pea-foundry-api-key" \
  --secrets \
    "pea-foundry-api-key=keyvaultref:${KV_URI}/secrets/pea-foundry-api-key,identityref:$IDENTITY_ID" \
  --output none
# Pass --args at trigger time:
#   az containerapp job start --name pea-backfill --resource-group pea-rg \
#     --args "--stage" "all" "--countries" "NG,ZA,UG,DZ" \
#            "--backfill-from" "2024-01-01" "--backfill-to" "2024-12-31" \
#            "--backfill-window-days" "30" "--workers" "8" \
#            "--upload-to" "abfss://pea-data/backfill"

# ── 8. Azure Monitor alert on job failure ─────────────────────────────────────
echo "--- Creating job-failure alert ---"
ACTION_GROUP_ID=$(az monitor action-group create \
  --name pea-alerts \
  --resource-group "$RESOURCE_GROUP" \
  --short-name peaalert \
  --action email pea-admin "$ALERT_EMAIL" \
  --query id --output tsv)

# Alert fires when a job execution ends in a Failed state.
az monitor scheduled-query create \
  --name pea-job-failure-alert \
  --resource-group "$RESOURCE_GROUP" \
  --scopes "$(az monitor log-analytics workspace show \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$LOG_WORKSPACE" --query id --output tsv)" \
  --condition "count > 0" \
  --condition-query "ContainerAppConsoleLogs_CL | where Log_s contains 'Pipeline failed'" \
  --window-size 10 \
  --evaluation-frequency 10 \
  --severity 2 \
  --action-groups "$ACTION_GROUP_ID" \
  --output none

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Daily job runs at 06:00 UTC. To trigger manually:"
echo "  az containerapp job start --name pea-daily --resource-group $RESOURCE_GROUP"
echo ""
echo "To run a backfill:"
echo "  az containerapp job start --name pea-backfill --resource-group $RESOURCE_GROUP \\"
echo "    --args \"--stage\" \"all\" \"--countries\" \"NG,ZA,UG,DZ\" \\"
echo "           \"--backfill-from\" \"2024-01-01\" \"--backfill-to\" \"2024-12-31\" \\"
echo "           \"--backfill-window-days\" \"30\" \"--workers\" \"8\" \\"
echo "           \"--upload-to\" \"abfss://$ADLS_FILESYSTEM/backfill\""
echo ""
echo "To watch execution logs:"
echo "  az containerapp job execution list --name pea-daily --resource-group $RESOURCE_GROUP --output table"
