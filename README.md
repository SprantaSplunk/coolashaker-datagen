# CoolaShaker Demo for Splunk

Three Splunk apps for the CoolaShaker demo (virtual coffee cup manufacturer with sites in
Vienna, Berlin, Atlanta and a Frankfurt data center).

| App | Version | Content |
|---|---|---|
| `TA-bar-datagen` | 1.9.0 | Demo data generators (Buttercup Bar, CoolaShaker, Network Intelligence). Start/stop from the Inputs page, sends via HEC or directly. |
| `splunk_app_coolashaker` | 1.4.0 | CoolaShaker dashboards (Classic Simple XML): manufacturing, SAP, infrastructure, network, web application, network assurance for AI workloads, plus alerts. |
| `coolashaker_studio` | 1.1.0 | Dashboard Studio redesign of the CoolaShaker app with custom Canvas visualizations. |

## Install

Ready-to-install packages are in [`dist/`](dist):

1. Splunk Web → **Apps → Manage Apps → Install app from file**, install all three `.tar.gz` files.
2. Create the indexes and a HEC token whose allowed indexes contain them (list in
   [`TA-bar-datagen/README.txt`](TA-bar-datagen/README.txt)).
3. Open **Demo Datagen → Setup → HEC Setup**, enter HEC URL and token, then enable the inputs.

The fault scenarios of the CoolaShaker input are individual checkboxes on the input and are
off by default.

## Layout

```
TA-bar-datagen/           add-on source
splunk_app_coolashaker/   Classic dashboard app source
coolashaker_studio/       Dashboard Studio app source
dist/                     installable packages (.tar.gz)
```

Credentials are never stored in this repository: the HEC token is entered on the setup page and
kept in Splunk's `storage/passwords`.
