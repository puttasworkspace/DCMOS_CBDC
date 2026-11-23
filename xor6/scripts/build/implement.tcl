# Constrained placement of the 60 CBDC macros (8 stages), then fixed routing.
# Same method as ../../../scripts/build/implement.tcl, with the stage count and
# core count taken from params.tcl:
#   chain column x (upper) / z (lower), rows y .. y+N  (entrance + N stages)
#   arbiter FF  (BFF) at (ax, y+N+1), excite FF (AFF) at (ax, y-1)
set root [file normalize [file join [file dirname [info script]] ..]]
set out $root/build
source $root/scripts/params.tcl
set_param general.maxThreads 2
open_checkpoint $out/synthesized.dcp
set cells [dict create]
foreach c [get_cells -hier] {dict set cells $c $c}
proc cell {name} {
 if {![dict exists $::cells $name]} {error "Expected one cell $name"}
 return [dict get $::cells $name]
}
proc locate {name site bel {pins ""}} {
 set c [cell $name];set_property BEL $bel $c;set_property LOC $site $c
 if {$pins ne ""} {set_property LOCK_PINS $pins $c}
}
set f [open $root/layout.tcl r];set layout [read $f];close $f
if {[llength $layout]!=$CORES} {error "Expected $CORES physical macros"}
set pb [create_pblock puf_sites]
set ranges {};set members {}
for {set i 0} {$i<$CORES} {incr i} {
 lassign [lindex $layout $i] x z y ax type
 set b [format {gen_core[%d].u_engine/u_core} $i]
 foreach side {upper lower} sx [list $x $z] {
  set ch $b/u_chain_$side
  locate $ch/gen_fixed_parity_gate.u_head_gate SLICE_X${sx}Y$y A6LUT {I0:A1 I1:A2}
  lappend ranges "SLICE_X${sx}Y${y}:SLICE_X${sx}Y[expr {$y+$N_STAGES}]"
  for {set j 0} {$j<$N_STAGES} {incr j} {
   set stage [format {%s/gen_elem[%d].u_elem/gen_style_p} $ch $j]
   set site SLICE_X${sx}Y[expr {$y+$j+1}]
   locate $stage.u_buf $site A6LUT {I0:A1 I1:A2}
   locate $stage.u_inv $site B6LUT {I0:A1 I1:A2}
   locate $stage.u_mux $site C6LUT {I0:A1 I1:A2 I2:A3}
  }
 }
 set arbsite SLICE_X${ax}Y[expr {$y+$N_STAGES+1}]
 set exsite SLICE_X${ax}Y[expr {$y-1}]
 locate $b/u_arbiter_dff $arbsite BFF
 set e [format {gen_core[%d].u_engine/u_ctrl/puf_excite_o_reg} $i]
 locate $e $exsite AFF
 lappend ranges $arbsite $exsite
 lappend members [cell $b] [cell $e]
 set p [get_pins -of_objects [cell $b/u_chain_upper/gen_fixed_parity_gate.u_head_gate] -filter {REF_PIN_NAME == O}]
 set_property ALLOW_COMBINATORIAL_LOOPS TRUE [get_nets -of_objects $p]
}
resize_pblock $pb -add $ranges
add_cells_to_pblock $pb $members
set_property EXCLUDE_PLACEMENT TRUE $pb
write_checkpoint -force $out/constrained.dcp
place_design
write_checkpoint -force $out/placed.dcp
source $root/scripts/route.tcl
