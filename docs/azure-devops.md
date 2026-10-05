# Azure DevOps pipeline

[`azure-pipelines.yml`](../azure-pipelines.yml) is the Azure DevOps equivalent of the [scheduled FinOps check](../README.md#scheduled-finops-check) in GitHub Actions:

- runs **every Monday at 06:17 UTC** on `main` (`always: true`, also without new commits) and on demand;
- logs in through an **Azure Resource Manager service connection with workload identity federation**, so no secret is stored anywhere. `AzureCLI@2` logs the Azure CLI in, and the finder's `DefaultAzureCredential` uses that login;
- runs `waste-finder --format md,html,json --summary …` against the connection's subscription;
- compares with the `report.json` of the previous run on `main`, so the report has a trend;
- publishes the report as pipeline artifact **`finops-report`** and puts the German summary on the run page.

It only reads, so it may run on a schedule. It never runs in GitHub; GitHub CI only checks that the file parses and keeps its structure (`tests/test_azure_pipelines.py`).

## 1. Identity: a read-only service principal with a federated credential

The pipeline needs Reader on the subscription for Resource Graph. For `costSource: actual` it also needs Cost Management Reader. Pick one of these options.

### Option A (recommended): reuse the identity from `infra/github-oidc`

That app registration already has exactly Reader + Cost Management Reader (see [Connect GitHub to Azure](../README.md#connect-github-to-azure)). It only needs a second federated credential for Azure DevOps.

1. In Azure DevOps go to **Project settings → Service connections → New service connection → Azure Resource Manager**.
2. Fill in:
   - **Identity type**: *App registration or managed identity (manual)*
   - **Credential**: *Workload identity federation*
   - **Service connection name**: `azure-waste-finder` (the name `azure-pipelines.yml` expects)
3. Click **Next**. The dialog now shows an **Issuer** and a **Subject identifier**. Copy both exactly; their format depends on your organization.
4. Add them to the app registration as a federated credential:

   ```bash
   cd infra/github-oidc
   cat > /tmp/ado-fic.json <<EOF
   {
     "name": "azure-devops",
     "issuer": "<Issuer from the dialog>",
     "subject": "<Subject identifier from the dialog>",
     "audiences": ["api://AzureADTokenExchange"],
     "description": "Azure DevOps service connection azure-waste-finder"
   }
   EOF
   az ad app federated-credential create --id "$(terraform output -raw client_id)" --parameters @/tmp/ado-fic.json
   ```

   Terraform does not manage this credential, so a later `terraform apply` leaves it alone. `terraform destroy` deletes it together with the app.
5. Finish the dialog:
   - **Scope level**: *Subscription*
   - **Subscription ID** / **name**: from `az account show`
   - **Application (client) ID**: `terraform output -raw client_id`
   - **Directory (tenant) ID**: `terraform output -raw tenant_id`

   Click **Verify and save**. Leave "Grant access permission to all pipelines" unchecked; the first run asks for permission instead.

### Option B: let Azure DevOps create the app registration, then make it read-only

*App registration (automatic)* with credential *Workload identity federation* and scope *Subscription* creates an app registration with **Contributor** on the subscription. That is more than a read-only tool needs, so swap the role. The app's ID is shown under the service connection → *Manage App registration*.

```bash
sub=$(az account show --query id -o tsv)
app=<application (client) ID of the service connection>
az role assignment create --assignee "$app" --role Reader --scope "/subscriptions/$sub"
az role assignment create --assignee "$app" --role "Cost Management Reader" --scope "/subscriptions/$sub"
az role assignment delete --assignee "$app" --role Contributor --scope "/subscriptions/$sub"
```

If you name the connection something other than `azure-waste-finder`, change the variable `azureServiceConnection` in `azure-pipelines.yml`. Service connections are resolved when the YAML is compiled, so a UI variable cannot replace it.

## 2. Create the pipeline

1. Go to **Pipelines → New pipeline**.
2. Choose where the code lives: **GitHub** (authorize the Azure Pipelines app for `viache25/azure-waste-finder`) or **Azure Repos Git** (after importing the repository).
3. Select the repository, then **Existing Azure Pipelines YAML file** → branch `main`, path `/azure-pipelines.yml` → **Continue**.
4. Click **Run**, or **Save** first and run it later. The first run stops with *"This pipeline needs permission to access a resource"*: choose **View → Permit** for the service connection.
5. The weekly schedule now shows under the pipeline's **⋮ → Scheduled runs**.

The very first run has no earlier report, so the step *Previous report* fails. `continueOnError` keeps the run going, but the run is marked *partially succeeded*, and the report has no trend. From the second run on, the trend is there.

## 3. Settings

| Setting | Where | Default | Meaning |
|---|---|---|---|
| `azureServiceConnection` | variable in `azure-pipelines.yml` | `azure-waste-finder` | Name of the service connection |
| `AZURE_SUBSCRIPTION_ID` | pipeline variable (UI), optional | the connection's subscription | Scan another subscription the identity can read |
| `costSource` | run parameter | `retail` | `actual` uses Cost Management amounts |
| `failOver` | run parameter | blank (never) | Fail the run when the monthly waste is above this amount (exit code 3). The report is still published, and Azure DevOps notifies you of the failed run. This is the counterpart of the GitHub issue |

Scheduled runs use the parameter defaults; change the defaults in the YAML to change scheduled behaviour. Rules, exclusions and currency come from a `waste-finder.toml` in the repository root, if there is one.

## 4. Results

- **Summary on the run page** (*Extensions* tab): the German summary "Azure Kostencheck" with the total per month and per year, the change since the last run, and one row per rule.
- **Artifact `finops-report`**: `report.md`, `report.html`, `report.json` and `summary.md`. The next run downloads `report.json` from here for the trend.
- **Cost**: a run takes about two minutes on a Microsoft-hosted agent. That is well inside the free tier (one parallel job; private projects get 1,800 minutes per month, and new organizations may have to request the free grant). Azure itself charges nothing, because the pipeline only reads.
