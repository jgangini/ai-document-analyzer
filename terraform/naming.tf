locals {
  bucket_name           = var.bucket_name != "" ? var.bucket_name : "buk-doc-ai-${var.deployment_suffix}"
  adb_db_name           = var.adb_db_name != "" ? var.adb_db_name : substr("docai${var.deployment_suffix}", 0, 14)
  adb_display_name      = var.adb_display_name != "" ? var.adb_display_name : "docai26ai-${var.deployment_suffix}"
  vcn_display_name      = var.vcn_display_name != "" ? var.vcn_display_name : "vcn-doc-ai-${var.deployment_suffix}"
  instance_display_name = var.instance_display_name != "" ? var.instance_display_name : "doc-analyzer-${var.deployment_suffix}"
}
