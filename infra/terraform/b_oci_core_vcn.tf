############################################
# Virtual Cloud Network
############################################

resource "oci_core_vcn" "vcn" {
  compartment_id = var.compartment_ocid
  display_name   = local.vcn_display_name
  cidr_block     = var._oci_vcn.cidr_block
}

resource "oci_core_subnet" "subnet" {
  cidr_block                 = var._oci_vcn.cidr_block
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.vcn.id
  display_name               = "public-subnet"
  prohibit_internet_ingress  = false
  prohibit_public_ip_on_vnic = false
  route_table_id             = oci_core_route_table.route_table.id
  security_list_ids          = [oci_core_security_list.vcn_security_list.id]
}

resource "oci_core_security_list" "vcn_security_list" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.vcn.id
  display_name   = "allow-document-analyzer"

  dynamic "ingress_security_rules" {
    for_each = var._oci_vcn.ingress_tcp_ports
    content {
      protocol = "6"
      source   = "0.0.0.0/0"

      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }

      description = "Allow TCP port ${ingress_security_rules.value}"
    }
  }

  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }
}

resource "oci_core_internet_gateway" "internet_gateway" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.vcn.id
  display_name   = "internet-gateway"
  enabled        = true
}

resource "oci_core_route_table" "route_table" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.vcn.id
  display_name   = "route-to-internet"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.internet_gateway.id
  }
}
