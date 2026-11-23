# Delay-audit worker: vivado -mode batch -source scripts/review_shard.tcl -tclargs <shard 0..3>
# Opens routed_refined.dcp and exports modeled delays of every PUF net for a
# quarter of the cores into build/audit/net_delays_shard_<n>.csv.
set root [file normalize [file join [file dirname [info script]] ..]]
source $root/scripts/params.tcl
set_param general.maxThreads 1
set shard [lindex $argv 0]
if {$shard eq "" || $shard<0 || $shard>3} {error "Expected audit shard 0..3"}
set out $root/build/audit
file mkdir $out
open_checkpoint $root/build/routed_refined.dcp
set f [open $out/net_delays_shard_$shard.csv w];puts $f {net,driver,sink,slow_max_ps,fast_min_ps}
set seen [dict create];set nc 0
foreach c [get_cells -hier -filter {IS_PRIMITIVE}] {
 if {![regexp {^gen_core\[([0-9]+)\]} $c -> i] || ($i*4)/$CORES!=$shard} {continue}
 if {[get_property REF_NAME $c] in {GND VCC}} {continue}
 if {![string match {*u_core/*} $c] && ![string match {*puf_excite_o_reg} $c] && ![string match {*puf_latch_o_reg} $c] && ![string match {*puf_clr_o_reg} $c]} {continue}
 foreach p [get_pins -of_objects $c -filter {DIRECTION == OUT}] {
  set n [get_nets -of_objects $p]
  foreach a [get_net_delays -of_objects $n] {
   set sink [get_property TO_PIN $a];set key "$p->$sink"
   if {[dict exists $seen $key]} {continue};dict set seen $key 1
   puts $f "$n,$p,$sink,[get_property SLOW_MAX $a],[get_property FAST_MIN $a]"
  }
  incr nc
 }
}
close $f
set f [open $out/net_delays_shard_$shard.complete w]
puts $f [format {%d %d %d} $shard $nc [dict size $seen]];close $f
puts "SHARD_COMPLETE $shard nets=$nc arcs=[dict size $seen]"
