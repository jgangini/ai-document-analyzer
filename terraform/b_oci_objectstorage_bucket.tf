############################################
# Object Storage bucket for document assets
############################################

resource "oci_objectstorage_bucket" "bucket" {
  compartment_id = var.compartment_ocid
  name           = local.bucket_name
  namespace      = var.objectstorage_namespace

  access_type  = var._oci_bucket_name.access_type
  storage_tier = "Standard"
}
