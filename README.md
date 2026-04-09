# OpenShift Operator Collector Tool

This tool automates the auditing of operators installed in an OpenShift cluster. It correlates cluster data (Subscriptions and ClusterServiceVersions) with the official **Red Hat Product Lifecycle** to identify support dates, maintenance windows, and Extended Update Support (EUS/ELS) information.

## Main Features

-   **Automated Collection**: Retrieves `subscriptions` and `csvs` from all namespaces using the `oc` CLI.
-   **Dynamic Lifecycle Sync**: Automatically downloads the latest Red Hat Lifecycle JSON data directly from the Customer Portal if not present locally.
-   **Smart Matching**: Uses fuzzy and normalized string matching to correlate cluster operator names with official Red Hat product entries.
-   **Comprehensive Phase Mapping**: Maps "Maintenance support" and "Extended Update Support Term" (1, 2, and 3) to clear report columns.
-   **Responsive Dashboard**: Generates a professional HTML report with sticky columns and Tailwind CSS styling, optimized for any screen size.

## Prerequisites

1.  **OpenShift CLI (`oc`)**: Must be installed and logged into an active cluster.
2.  **Python 3.x**: Required to execute the script.
3.  **Network Access**: Access to `access.redhat.com` is required for the automated lifecycle data download.

## Installation

Clone the repository to your local machine or bastion host:

```bash
$ git clone https://github.com/mariorpn/collector-operators-tool.git
$ cd collector-operators-tool
```

## Usage

Execute the main script:
```
$ python3 coletor_operadores.py
```

### Execution Logic

1. **Lifecycle Verification:** Checks for a local file matching `product_lifecycle_data_YYYY-MM-DD.json`. If missing, it initiates an automated download via the Red Hat Portal.

2. **Cluster Discovery:** Executes `oc get subs -A` and `oc get csv -A` to gather OLM inventory.

3. **Filtering:** By default, it processes operators for OpenShift versions 4.14 and above.

4. **Report Generation:** Produces two files in the execution directory: a CSV for auditing and an HTML dashboard for visualization.

## Output Files

- **`operator_inventory_report.csv`:** Semicolon-separated file for Excel auditing.

- **`operator_report.html`:** A dynamic web-based dashboard with horizontal and vertical scrolling.

- **`cache_*.json`:** Local cache files used to speed up repeated runs and reduce API calls.

## Troubleshooting

- **Empty Results:** Ensure your `oc` user has cluster-wide read permissions for subscriptions and CSVs.

- **N/A Values:** If a product shows "N/A" for lifecycle, ensure the operator name is similar to the Red Hat product name or verify the product exists in the downloaded `product_lifecycle_data.json` file.