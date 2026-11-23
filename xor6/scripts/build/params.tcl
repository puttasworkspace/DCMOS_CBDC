# Shared parameters for the XOR-6 build (sourced by every build script).
# The scripts run inside an isolated stage folder prepared by build_xor6.ps1:
#   rtl/  scripts/  basys3_xor6.xdc  layout.tcl  layout.json
#   internal_route_template.tcl  build/
set N_STAGES 8
set CORES    60
set TOP      cbdc_xor6_serial
set PART     xc7a35tcpg236-1
set BITFILE  xor6_array60.bit
# 1 = characterisation build (per-core voted bits in every reply; needed for key
#     enrollment in the staged version). 0 = deployment build (only the 10 XOR
#     bits leave the chip). build_xor6.ps1 -HideCoreBits sets 0.
set EXPOSE_CORE_BITS 1
# Route-template records per core: 2 chains x (entrance + 3*(N-1) + buf/inv of last stage)
set TEMPLATE_RECORDS [expr {2*(1 + 3*($N_STAGES-1) + 2)}]
# Paired internal arcs per core (head->buf/inv, buf/inv->mux, mux->next buf/inv)
set PAIRED_ARCS_PER_CORE [expr {4*$N_STAGES}]
