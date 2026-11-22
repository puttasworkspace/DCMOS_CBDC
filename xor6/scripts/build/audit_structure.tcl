# Structural audit of every placed/routed macro (sourced with root, out, layout,
# cells/cell, CORES, N_STAGES available). Fails on the first deviation.
proc driver {c pin} {
 set p [get_pins -of_objects $c -filter [format {REF_PIN_NAME == "%s"} $pin]]
 return [get_pins -leaf -of_objects [get_nets -of_objects $p] -filter {DIRECTION == OUT}]
}
if {![info exists cells]} {set cells [dict create];foreach c [get_cells -hier] {dict set cells $c $c}}
if {[info procs cell] eq ""} {proc cell {n} {return [dict get $::cells $n]}}
set last [expr {$N_STAGES-1}]
set allffs [get_cells -hier -filter {REF_NAME =~ FD*}]
set f [open $out/structure.txt w]
for {set i 0} {$i<$CORES} {incr i} {
 lassign [lindex $layout $i] x z y ax type
 set base [format {gen_core[%d].u_engine/u_core} $i];set ffs {}
 foreach ff $allffs {if {[string first "$base/" $ff]==0} {lappend ffs $ff}}
 if {[llength $ffs]!=1} {error "Core $i: expected exactly ONE core FF"}
 set arb [cell $base/u_arbiter_dff]
 if {[get_property LOC $arb] ne "SLICE_X${ax}Y[expr {$y+$N_STAGES+1}]" || ![string match *BFF [get_property BEL $arb]]} {error "Core $i: wrong arbiter placement"}
 set ex [cell [format {gen_core[%d].u_engine/u_ctrl/puf_excite_o_reg} $i]]
 if {[get_property LOC $ex] ne "SLICE_X${ax}Y[expr {$y-1}]" || ![string match *AFF [get_property BEL $ex]]} {error "Core $i: wrong excitation placement"}
 if {[get_property IS_C_INVERTED $arb] ni {1 1'b1 TRUE true}} {error "Core $i: wrong arbiter edge"}
 foreach pin {D C CE CLR} expected [list [format {%s/u_chain_upper/gen_elem[%d].u_elem/gen_style_p.u_mux/O} $base $last] [format {%s/u_chain_lower/gen_elem[%d].u_elem/gen_style_p.u_mux/O} $base $last] [format {gen_core[%d].u_engine/u_ctrl/puf_latch_o_reg/Q} $i] [format {gen_core[%d].u_engine/u_ctrl/puf_clr_o_reg/Q} $i]] {
  if {"[driver $arb $pin]" ne $expected} {error "Core $i: wrong arbiter $pin"}
 }
 foreach side {upper lower} sx [list $x $z] {
  set head [cell $base/u_chain_$side/gen_fixed_parity_gate.u_head_gate]
  if {[get_property LOC $head] ne "SLICE_X${sx}Y${y}" || ![string match *A6LUT [get_property BEL $head]] || [lsort [get_property LOCK_PINS $head]] ne [lsort {I0:A1 I1:A2}]} {error "Core $i: wrong entrance placement/pins"}
  if {![string equal -nocase [get_property INIT $head] "4'h8"]} {error "Core $i: wrong head gate"}
  set other [expr {$side eq "upper" ? "lower" : "upper"}]
  if {"[driver $head I0]" ne [format {gen_core[%d].u_engine/u_ctrl/puf_excite_o_reg/Q} $i]} {error "Core $i: wrong entrance excitation"}
  if {"[driver $head I1]" ne [format {%s/u_chain_%s/gen_elem[%d].u_elem/gen_style_p.u_mux/O} $base $other $last]} {error "Core $i: wrong cross feedback"}
  for {set j 0} {$j<$N_STAGES} {incr j} {
   foreach kind {buf inv mux} init {4'hA 4'h5 8'hCA} bel {A6LUT B6LUT C6LUT} pins {{I0:A1 I1:A2} {I0:A1 I1:A2} {I0:A1 I1:A2 I2:A3}} {
    set c [cell [format {%s/u_chain_%s/gen_elem[%d].u_elem/gen_style_p.u_%s} $base $side $j $kind]]
    if {![string equal -nocase [get_property INIT $c] $init] || [get_property LOC $c] ne "SLICE_X${sx}Y[expr {$y+$j+1}]" || ![string match "*$bel" [get_property BEL $c]] || [lsort [get_property LOCK_PINS $c]] ne [lsort $pins]} {error "Wrong stage implementation $c"}
    set stage [format {%s/u_chain_%s/gen_elem[%d].u_elem/gen_style_p} $base $side $j]
    if {$kind eq "mux"} {
     if {"[driver $c I0]" ne "$stage.u_buf/O" || "[driver $c I1]" ne "$stage.u_inv/O"} {error "Wrong buffer/inverter mux inputs $c"}
     set expected [format {gen_core[%d].u_engine/u_ctrl/puf_c_o_reg[%d]/Q} $i $j]
     if {"[driver $c I2]" ne $expected} {error "Wrong configuration select $c"}
    } else {
     set prev [expr {$j==0 ? "$base/u_chain_$side/gen_fixed_parity_gate.u_head_gate/O" : [format {%s/u_chain_%s/gen_elem[%d].u_elem/gen_style_p.u_mux/O} $base $side [expr {$j-1}]]}]
     if {"[driver $c I0]" ne $prev} {error "Broken stage cascade $c"}
    }
   }
  }
 }
 puts $f "Core $i PASS: one falling-edge FF; D/clock/Latch/clear wiring; fixed AND; $N_STAGES stage truth tables, sites/BELs/pins; all configuration selects."
}
close $f
puts "XOR6_STRUCTURE_AUDIT_PASS $CORES cores"
