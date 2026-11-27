# Changelog

Every release of the apps and of the ITSI content pack, newest first. Each release has a git tag
(`TA-bar-datagen-<version>`, `splunk_app_coolashaker-<version>`, `coolashaker_studio-<version>`,
`itsi-<date><letter>`), so the full difference between two releases is

    git diff TA-bar-datagen-1.9.0 TA-bar-datagen-1.9.1 -- TA-bar-datagen

Installable packages of the current versions are in `dist/`, the content pack is in `itsi/`.

## 2026-11-27

### coolashaker_studio 1.1.1
- Fixed: clicking a site no longer opened the target dashboard unfiltered (the link set
  `form.form.site` instead of `form.site`). Affected: *Every site to every site* (Network
  Intelligence → Catalyst Center), *Site mesh* (ThousandEyes), *Sites & DC paths* (Home → Executive),
  *Campus health by site* (Executive → Catalyst Center) and *Web error rate by site* (Executive → Web).
- Action: install `dist/coolashaker_studio-1.1.1.tar.gz` as an upgrade. No restart needed;
  reload the dashboards in the browser.

## 2026-11-26

### TA-bar-datagen 1.9.2
- Fixed: creating a new *CoolaShaker* input still failed with "The following required arguments
  are missing: scenario_ai_fabric." (the 1.9.1 fix did not help). Splunk requires every setting
  listed in `inputs.conf.spec` when an input is created, but the input form has no field for this
  setting, unused since 1.7.0. It is now removed completely.
- Action: install `dist/TA-bar-datagen-1.9.2.tar.gz` as an upgrade and restart Splunk. Setup and
  inputs are kept. Older inputs may still contain `scenario_ai_fabric` in `local/inputs.conf`;
  the line is ignored and can be deleted.

### TA-bar-datagen 1.9.1
- Fixed: creating a new *CoolaShaker* input on a fresh Splunk instance failed with "The following
  required arguments are missing: scenario_ai_fabric." The setting has not been used since 1.7.0
  but was still listed in `inputs.conf.spec` without a default. Existing inputs were not affected.
- Action: install `dist/TA-bar-datagen-1.9.1.tar.gz` as an upgrade and restart Splunk. Setup and
  inputs are kept.

## 2026-11-20

### ITSI content pack (itsi-20261120a)
- New: ITSI content pack `itsi/DA-ITSI-CP-CUST-6b0004cfb39a5c132421fbc5_1_0_0.tar.gz`
  (*coolashaker_inkl_conf* 1.0.0, ITSI 5.0.3) with the complete service trees: 82 services
  (`CoolaShaker`, `Atlanta`, `Berlin`, `Vienna` with their site services, `SAP ERP`,
  `Supporthotline`, `Collaboration - Microsoft Teams`, the Buttercup Bar services), 30 KPI base
  searches, 15 service templates and 5 entity types.
- Action: install TA-bar-datagen 1.9.0 first and let it run, then install the file as an app
  (*Apps → Manage Apps → Install app from file*) and install its objects in
  *ITSI → Configuration → Data Integrations → Content Library*.

## 2026-11-18

First release in this repository: the CoolaShaker demo without the Cisco Live lab content.

### TA-bar-datagen 1.9.0
- Data generators for Buttercup Bar, CoolaShaker (manufacturing, SAP ERP and MII, Windows,
  VMware, MSSQL, Microsoft Teams, ThousandEyes, Meraki, Catalyst) and Network Intelligence
  (Meraki, Catalyst Center, ThousandEyes, SC4SNMP). Indexes and sourcetypes as listed in
  `TA-bar-datagen/README.txt`.
- CoolaShaker fault scenarios are individual checkboxes on the input, all off by default,
  including *SAP IDoc interface ERP → MII broken* (`scenario_sap_idoc`).
- The Network Intelligence input has no *Enable failures* setting.
- Action: install `dist/TA-bar-datagen-1.9.0.tar.gz`, enter HEC URL and token in
  *Setup → HEC Setup* and add all indexes to the *allowed indexes* of the HEC token. If an earlier
  version with *Enable failures* was installed, remove `enable_failures` from
  `local/inputs.conf` of the Network Intelligence input.

### splunk_app_coolashaker 1.4.0
- CoolaShaker dashboards (Classic Simple XML) for manufacturing, SAP ERP & MII, infrastructure,
  network, web application and network assurance for AI workloads, plus proactive alerts.
- No lab guide, no *Lab Solutions* dashboard and no *Cisco Live Lab* menu. The *ITSI Service
  Tree* link is at the end of the *CoolaShaker* menu.
- Action: install `dist/splunk_app_coolashaker-1.4.0.tar.gz`. When upgrading from a lab version,
  delete `local/` copies of `lab_guide` and `lab_solutions` (*Settings → User interface → Views*).

### coolashaker_studio 1.1.0
- Dashboard Studio redesign of the CoolaShaker dashboards with custom Canvas visualizations.
- No *Lab Guide* and *Lab Solutions* pages and no *Cisco Live Lab* menu. The *ITSI Service Tree*
  link is in the *Search* menu.
- Action: install `dist/coolashaker_studio-1.1.0.tar.gz`. When upgrading from a lab version,
  delete `local/` copies of `cs_lab_guide` and `cs_lab_solutions`.
