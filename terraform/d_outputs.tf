output "application_url" {
  description = "AI Document Analyzer public URL."
  value       = "http://${oci_core_instance.linux_instance.public_ip}"
}

output "ssh_user" {
  description = "SSH user for the compute instance."
  value       = "opc"
}

output "adb_db_name" {
  description = "Autonomous Database name created for AI Document Analyzer."
  value       = oci_database_autonomous_database.ora26ai.db_name
}

output "autonomous_database_id" {
  description = "Autonomous Database OCID created for AI Document Analyzer."
  value       = oci_database_autonomous_database.ora26ai.id
}

output "bucket_name" {
  description = "Object Storage bucket created for AI Document Analyzer."
  value       = oci_objectstorage_bucket.bucket.name
}
