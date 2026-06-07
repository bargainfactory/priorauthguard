# Example tenant policy bundle for PriorAuthGuard's OPA overlay.
#
# Load this into an OPA server so the `OpaPolicyEngine` can call it:
#
#     opa run --server policies/
#
# `OpaPolicyEngine` queries `pa_guard/tenants/<tenant_id>/findings`.
# The package below registers under `pa_guard.tenants.acme`; clone +
# rename the package for each tenant.

package pa_guard.tenants.acme

# Severity levels mirror the platform's: "info" | "warning" | "blocker".

# --- Custom blocker: biologics require PCP attestation ------------------------
findings contains {
  "rule_id":  "ACME-BIO-001",
  "severity": "blocker",
  "message":  "Biologic agents require an attached PCP attestation under ACME's policy."
} if {
  is_biologic_procedure
  not has_pcp_attestation
}

# --- Custom warning: lumbar ESI requires conservative-therapy duration ≥ 6w -
findings contains {
  "rule_id":  "ACME-LUMBAR-001",
  "severity": "warning",
  "message":  "ACME requires 6 weeks of documented conservative therapy for CPT 64483."
} if {
  input.request.meta.procedure_code == "64483"
  not narrative_mentions_six_weeks
}

# --- Custom info: payer-specific routing reminder ----------------------------
findings contains {
  "rule_id":  "ACME-ROUTE-001",
  "severity": "info",
  "message":  "ACME routes all UHC requests via Availity even on UHC.com."
} if {
  lower_payer == "uhc"
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

is_biologic_procedure if {
  codes := {"J1602", "J1745", "J3262", "J9035"}   # representative biologic J-codes
  codes[input.request.meta.procedure_code]
}

has_pcp_attestation if {
  contains(lower(input.document.medical_necessity_narrative), "pcp attestation")
}

narrative_mentions_six_weeks if {
  contains(lower(input.document.medical_necessity_narrative), "6 weeks")
}

lower_payer := lower(input.request.meta.payer_id)
