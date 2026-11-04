# Databricks notebook source
# MAGIC %md
# MAGIC # Setup — run once
# MAGIC Creates the Unity Catalog objects the pipeline expects. Names must match `config/pipeline_config.yml`.
# MAGIC If your workspace doesn't let you create a catalog, change `catalog` in the config to one you can use
# MAGIC and skip the first statement.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE CATALOG IF NOT EXISTS ifc_cfo;
# MAGIC CREATE SCHEMA IF NOT EXISTS ifc_cfo.landing   COMMENT 'Landing zone for incoming source files';
# MAGIC CREATE SCHEMA IF NOT EXISTS ifc_cfo.ops       COMMENT 'Pipeline operations: schema gate and data-quality logs';
# MAGIC CREATE SCHEMA IF NOT EXISTS ifc_cfo.raw       COMMENT 'Raw: source files loaded as-is';
# MAGIC CREATE SCHEMA IF NOT EXISTS ifc_cfo.validated COMMENT 'Validated: typed, standardized, flagged; quarantine tables';
# MAGIC CREATE SCHEMA IF NOT EXISTS ifc_cfo.enriched  COMMENT 'Enriched: structured fields extracted from project descriptions';
# MAGIC CREATE SCHEMA IF NOT EXISTS ifc_cfo.defined  COMMENT 'Defined: business-ready tables and views used by Genie and the app';
# MAGIC CREATE VOLUME IF NOT EXISTS ifc_cfo.landing.files COMMENT 'incoming/, accepted/, held/ folders';

# COMMAND ----------

import os

for folder in ["incoming", "accepted", "held", "loaded", "config", "contracts"]:
    os.makedirs(f"/Volumes/ifc_cfo/landing/files/{folder}", exist_ok=True)

print("Ready. Now upload:\n  pipeline_config.yml -> /Volumes/ifc_cfo/landing/files/config/\n  both contract .yml files -> /Volumes/ifc_cfo/landing/files/contracts/\n  both CSVs -> /Volumes/ifc_cfo/landing/files/incoming/")
