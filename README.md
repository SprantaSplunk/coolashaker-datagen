# CoolaShaker Demo for Splunk

Three Splunk apps for the CoolaShaker demo (virtual coffee cup manufacturer with sites in
Vienna, Berlin, Atlanta and a Frankfurt data center).

| App | Version | Content |
|---|---|---|
| `TA-bar-datagen` | 1.9.0 | Demo data generators (Buttercup Bar, CoolaShaker, Network Intelligence). Start/stop from the Inputs page, sends via HEC or directly. |
| `splunk_app_coolashaker` | 1.4.0 | CoolaShaker dashboards (Classic Simple XML): manufacturing, SAP, infrastructure, network, web application, network assurance for AI workloads, plus alerts. |
| `coolashaker_studio` | 1.1.0 | Dashboard Studio redesign of the CoolaShaker app with custom Canvas visualizations. |
| `itsi/DA-ITSI-CP-CUST-6b0004cfb39a5c132421fbc5_1_0_0.tar.gz` | 1.0.0 | ITSI content pack with the complete CoolaShaker and Buttercup Bar service trees. |

Changes per release: [CHANGELOG.md](CHANGELOG.md). Every release has a git tag
(`TA-bar-datagen-<version>`, `splunk_app_coolashaker-<version>`, `coolashaker_studio-<version>`,
`itsi-<date><letter>`).

## Install

Ready-to-install packages are in [`dist/`](dist):

1. Splunk Web → **Apps → Manage Apps → Install app from file**, install all three `.tar.gz` files.
2. Create the indexes and a HEC token whose allowed indexes contain them (list in
   [`TA-bar-datagen/README.txt`](TA-bar-datagen/README.txt)).
3. Open **Demo Datagen → Setup → HEC Setup**, enter HEC URL and token, then enable the inputs.

The fault scenarios of the CoolaShaker input are individual checkboxes on the input and are
off by default.

## ITSI service tree (optional)

`itsi/DA-ITSI-CP-CUST-6b0004cfb39a5c132421fbc5_1_0_0.tar.gz` (title *coolashaker_inkl_conf*,
exported from ITSI 5.0.3 on Splunk 10.6.1.1) contains 82 services (`CoolaShaker`, `Atlanta`,
`Berlin`, `Vienna` with their site services, `SAP ERP`, `Supporthotline`,
`Collaboration - Microsoft Teams`, the Buttercup Bar services), 30 KPI base searches,
15 service templates and 5 entity types.

1. Install the data generator first and let it run, so the KPIs have data.
2. Install the file as an app (*Apps → Manage Apps → Install app from file*).
3. Install its objects in *ITSI → Configuration → Data Integrations → Content Library*.

## Layout

```
TA-bar-datagen/           add-on source
splunk_app_coolashaker/   Classic dashboard app source
coolashaker_studio/       Dashboard Studio app source
dist/                     installable packages (.tar.gz)
itsi/                     ITSI content pack (.tar.gz)
CHANGELOG.md              changes per release
```

Credentials are never stored in this repository: the HEC token is entered on the setup page and
kept in Splunk's `storage/passwords`.
