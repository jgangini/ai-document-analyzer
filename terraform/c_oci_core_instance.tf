############################################
# Compute host for AI Document Analyzer
############################################

resource "tls_private_key" "instance_ssh" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

data "oci_core_images" "oracle_linux" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Oracle Linux"
  operating_system_version = "9"
  shape                    = var._oci_instance.shape.name
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

resource "oci_core_instance" "linux_instance" {
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[var.availability_domain_index].name
  compartment_id      = var.compartment_ocid
  shape               = var._oci_instance.shape.name
  display_name        = local.instance_display_name

  lifecycle {
    ignore_changes = [
      source_details[0].source_id,
    ]
  }

  source_details {
    source_id   = data.oci_core_images.oracle_linux.images[0].id
    source_type = "image"
  }

  dynamic "shape_config" {
    for_each = var._oci_instance.shape.ocpus == null && var._oci_instance.shape.memory_in_gbs == null ? [] : [1]

    content {
      memory_in_gbs = var._oci_instance.shape.memory_in_gbs
      ocpus         = var._oci_instance.shape.ocpus
    }
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.subnet.id
    assign_public_ip = true
  }

  metadata = {
    ssh_authorized_keys = tls_private_key.instance_ssh.public_key_openssh
    user_data = base64encode(templatefile("${path.module}/templatefile/user_data.sh", {
      source_repo_url = var.source_repo_url
      source_ref      = var.source_ref
    }))
  }
}

resource "null_resource" "wait_for_userdata" {
  depends_on = [oci_core_instance.linux_instance]

  triggers = {
    instance_id = oci_core_instance.linux_instance.id
  }

  connection {
    type        = "ssh"
    host        = oci_core_instance.linux_instance.public_ip
    user        = "opc"
    private_key = tls_private_key.instance_ssh.private_key_pem
    timeout     = "40m"
  }

  provisioner "remote-exec" {
    inline = [
      <<-EOT
      for attempt in $(seq 1 480); do
        if [ -f /var/local/userdata.done ]; then
          exit 0
        fi

        status="$(sudo cloud-init status --long 2>/dev/null || true)"
        if echo "$status" | grep -q "status: error"; then
          printf '%s\n' "cloud-init failed before /var/local/userdata.done was created."
          printf '%s\n' "$status"
          sudo tail -n 200 /var/log/cloud-init-output.log || true
          exit 1
        fi
        sleep 5
      done

      printf '%s\n' "Timed out waiting for /var/local/userdata.done."
      sudo tail -n 200 /var/log/cloud-init-output.log || true
      exit 1
      EOT
      ,
      "cat /home/opc/startup_info.txt | sed 's/\\[PUBLIC-IP\\]/${oci_core_instance.linux_instance.public_ip}/g'",
    ]
  }
}

resource "null_resource" "configure_ai_document_analyzer" {
  depends_on = [
    null_resource.wait_for_userdata,
    oci_database_autonomous_database_wallet.adb_wallet,
    oci_objectstorage_bucket.bucket,
  ]

  triggers = {
    instance_id = oci_core_instance.linux_instance.id
    wallet_id   = oci_database_autonomous_database_wallet.adb_wallet.id
    bucket_name = oci_objectstorage_bucket.bucket.name
  }

  connection {
    type        = "ssh"
    host        = oci_core_instance.linux_instance.public_ip
    user        = "opc"
    private_key = tls_private_key.instance_ssh.private_key_pem
    timeout     = "40m"
  }

  provisioner "remote-exec" {
    inline = ["mkdir -p /home/opc/ctn-bootstrap && chmod 700 /home/opc/ctn-bootstrap"]
  }

  provisioner "file" {
    source      = "${path.module}/.oci/key.pem"
    destination = "/home/opc/ctn-bootstrap/key.pem"
  }

  provisioner "file" {
    source      = "${path.module}/.oci/config"
    destination = "/home/opc/ctn-bootstrap/config"
  }

  provisioner "remote-exec" {
    inline = [
      templatefile("${path.module}/templatefile/configure_app.sh", {
        adb_admin_password      = var.autonomous_database_admin_password
        adb_wallet_b64          = oci_database_autonomous_database_wallet.adb_wallet.content
        adb_wallet_password     = var.autonomous_database_wallet_password
        application_username    = var.application_username
        application_password    = var.autonomous_database_developer_password
        bucket_name             = oci_objectstorage_bucket.bucket.name
        compartment_ocid        = var.compartment_ocid
        objectstorage_namespace = var.objectstorage_namespace
        region                  = var.region
      })
    ]
  }
}
