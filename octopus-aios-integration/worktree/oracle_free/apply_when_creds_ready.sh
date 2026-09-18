#!/bin/bash
# Run AFTER credentials are in /etc/octopus/oracle.env AND
# explicit human "yes" in current session.
set -e
[ ! -f /etc/octopus/oracle.env ] && { echo "ERR: /etc/octopus/oracle.env missing"; exit 1; }
source /etc/octopus/oracle.env

export TF_VAR_tenancy_ocid TF_VAR_user_ocid TF_VAR_fingerprint
export TF_VAR_private_key_path TF_VAR_compartment_ocid
export TF_VAR_ssh_public_key_path=/root/.ssh/id_ed25519.pub

WORK=/opt/octopus/oracle_free
cd "$WORK"
cp -n oci_provision.tf.template main.tf
[ ! -d .terraform ] && terraform init
echo "--- terraform plan ---"
terraform plan -out=tfplan
echo
echo "Review the plan above. To apply, run manually:"
echo "  cd $WORK && terraform apply tfplan"
