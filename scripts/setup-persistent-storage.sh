#!/bin/bash
# Run ONCE to attach a persistent Azure Files volume at /data.
# After this, redeploys preserve the SQLite databases.
set -e

source .env

RG=rg-whatsapp-agent
APP=whatsapp-agent
ENV=env-whatsapp-agent
STORAGE_ACCOUNT=whatsappagentdata$RANDOM   # unique name
SHARE=whatsapp-agent-data
VOLUME=data-volume

echo "📦 Creating Azure Storage Account..."
az storage account create \
  --name $STORAGE_ACCOUNT \
  --resource-group $RG \
  --sku Standard_LRS \
  --kind StorageV2 \
  --output none

echo "📁 Creating file share..."
az storage share-rm create \
  --name $SHARE \
  --storage-account $STORAGE_ACCOUNT \
  --quota 1 \
  --output none

STORAGE_KEY=$(az storage account keys list \
  --account-name $STORAGE_ACCOUNT \
  --resource-group $RG \
  --query "[0].value" -o tsv)

echo "🔗 Linking storage to Container Apps environment..."
az containerapp env storage set \
  --name $ENV \
  --resource-group $RG \
  --storage-name $VOLUME \
  --azure-file-account-name $STORAGE_ACCOUNT \
  --azure-file-account-key "$STORAGE_KEY" \
  --azure-file-share-name $SHARE \
  --access-mode ReadWrite \
  --output none

echo "💾 Attaching volume to container app..."
# Export current app definition, inject volume + volumeMount, re-apply
TMPFILE=$(mktemp /tmp/ca-patch.XXXXXX.yaml)
az containerapp show --name $APP --resource-group $RG -o yaml > "$TMPFILE"

# Inject volumes block (idempotent — overwrites if already present)
python3 - "$TMPFILE" "$VOLUME" <<'PYEOF'
import sys, yaml

path = sys.argv[1]
vol  = sys.argv[2]

with open(path) as f:
    doc = yaml.safe_load(f)

tpl = doc["properties"]["template"]

# volumes
tpl.setdefault("volumes", [])
tpl["volumes"] = [v for v in tpl["volumes"] if v.get("name") != vol]
tpl["volumes"].append({"name": vol, "storageName": vol, "storageType": "AzureFile"})

# volumeMounts on the first container
for c in tpl.get("containers", []):
    c.setdefault("volumeMounts", [])
    c["volumeMounts"] = [m for m in c["volumeMounts"] if m.get("volumeName") != vol]
    c["volumeMounts"].append({"volumeName": vol, "mountPath": "/data"})

with open(path, "w") as f:
    yaml.dump(doc, f, default_flow_style=False, allow_unicode=True)
PYEOF

az containerapp update --name $APP --resource-group $RG --yaml "$TMPFILE" --output none
rm -f "$TMPFILE"

echo ""
echo "✅ Persistent volume attached!"
echo "   /data inside the container now maps to Azure Files share: $SHARE"
echo "   Storage account: $STORAGE_ACCOUNT"
echo "   Data survives all future redeploys."
