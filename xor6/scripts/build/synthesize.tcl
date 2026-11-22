# Synthesis of the XOR-6 top level (60 cores x 8 stages).
set root [file normalize [file join [file dirname [info script]] ..]]
set out $root/build
source $root/scripts/params.tcl
file mkdir $out
set_param general.maxThreads 2
create_project -in_memory -part $PART
foreach f [lsort [glob $root/rtl/*.v]] {read_verilog $f}
read_xdc $root/basys3_xor6.xdc
synth_design -top $TOP -part $PART -flatten_hierarchy none -generic EXPOSE_CORE_BITS=$EXPOSE_CORE_BITS
puts "EXPOSE_CORE_BITS=$EXPOSE_CORE_BITS"
opt_design
write_checkpoint -force $out/synthesized.dcp
report_utilization -file $out/utilization_synth.rpt
report_utilization -hierarchical -file $out/hierarchy_synth.rpt
puts "XOR6_SYNTHESIS_COMPLETE"
