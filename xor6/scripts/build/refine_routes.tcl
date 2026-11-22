# Run on the routed checkpoint (sourced after implement.tcl, or from a resume
# script that opened routed.dcp). Same targeted corrections as the 64-core
# flow, limited to stages that exist in an 8-stage chain:
#   - right-hand (_R) tiles: replace the mux->next-stage route (stages 0..N-2)
#   - CLBLM tiles: fixed buffer/inverter->mux route for stages 5 and 7
# The delay audit afterwards decides whether matching is complete; if it reports
# mismatched pairs, add corrections here for those stages and rerun.
set root [file normalize [file join [file dirname [info script]] ..]]
set out $root/build
source $root/scripts/params.tcl
set f [open $root/layout.tcl r];set layout [read $f];close $f
set cells [dict create];foreach c [get_cells -hier] {dict set cells $c $c}
proc cell {n} {return [dict get $::cells $n]}
set pins [dict create];foreach p [get_pins -hier] {dict set pins $p $p}
set replacements [dict create]
for {set i 0} {$i<$CORES} {incr i} {
 lassign [lindex $layout $i] x z y ax type
 set family [expr {[string match CLBLM_* $type] ? "CLBLM" : "CLBLL"}]
 foreach side {upper lower} {
  if {[string match *_R $type]} {
   for {set j 0} {$j<$N_STAGES-1} {incr j} {
    set p [dict get $pins [format {gen_core[%d].u_engine/u_core/u_chain_%s/gen_elem[%d].u_elem/gen_style_p.u_mux/O} $i $side $j]]
    set route [string map [list FAM $family] { { FAM_L_C FAM_LOGIC_OUTS10 NN2BEG2 SR1BEG2 { IMUX6 FAM_L_A1 } IMUX14 FAM_L_B1 } }]
    dict set replacements [get_nets -of_objects $p] $route
   }
  }
  if {$family eq "CLBLM" && [string match *_R $type]} {
   foreach j {5 7} {
    if {$j>=$N_STAGES} {continue}
    set p [dict get $pins [format {gen_core[%d].u_engine/u_core/u_chain_%s/gen_elem[%d].u_elem/gen_style_p.u_inv/O} $i $side $j]]
    dict set replacements [get_nets -of_objects $p] { { CLBLM_L_B CLBLM_LOGIC_OUTS9 BYP_ALT4 BYP_BOUNCE4 IMUX20 CLBLM_L_C2 } }
   }
  }
 }
}
puts "Refining [dict size $replacements] internal nets; preserving the other fixed routes"
set ns [dict keys $replacements]
if {[llength $ns]} {
 foreach n $ns {reset_property FIXED_ROUTE $n}
 route_design -unroute -nets $ns
 dict for {n route} $replacements {set_property FIXED_ROUTE $route $n}
 route_design
}
write_checkpoint -force $out/routed_refined.dcp
report_route_status -file $out/route_status_refined.rpt
report_timing_summary -report_unconstrained -file $out/timing_refined.rpt
report_drc -file $out/drc_refined.rpt
report_methodology -file $out/methodology_refined.rpt
source $root/scripts/audit_structure.tcl
write_verilog -force $out/implemented_refined.v
puts "XOR6_REFINED_ROUTING_COMPLETE"
