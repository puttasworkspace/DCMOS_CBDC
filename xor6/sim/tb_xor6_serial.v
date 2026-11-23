`timescale 1ns/1ps
// Functional test of cbdc_xor6_serial: UART framing and checksums, real
// Latch-controlled capture through the FDCE_1 model, on-chip majority voting,
// unanimity flags, group XOR, configuration readback, parallel and sequential
// activation, request rejection (parity / votes / control) and parser recovery.
//
// Qu/Qb are forced with controlled waveforms (as in ../../sim/tb_array64.v).
// This tests the digital logic only; it is not a model of physical delays.
module tb_xor6_serial;
 parameter integer EXPOSE=1;   // run_sim.py also runs EXPOSE=0 (deployment build)
 localparam integer CORES=60, GROUPS=10, GSIZE=6, REQ=64, REP=83;
 reg clk=0,btnU=0,uart_rx=1;wire uart_tx;wire [15:0] led;
 always #5 clk=~clk;
 cbdc_xor6_serial #(.UART_CLKS(8),.TIMEOUT_CYCLES(2000000),.EXPOSE_CORE_BITS(EXPOSE)) dut(.*);

 reg [59:0] expected_word=60'h963CA5F081E7426;
 reg [7:0]  cur_votes=0;
 event clear_ev;
 integer busy_count,h;reg saw_parallel=0;

 // Per-core stimulus. Cores with index%5==0 return the WRONG bit on their
 // first run (votes>=3) and also on their last run (votes>=5). That is always a
 // minority, so the majority must still be correct (an implementation that
 // copies the first or last run fails) and the unanimity flag must drop. An earlier, un-latched Qb edge is generated at
 // each Excite to check that capture follows Latch.
 genvar g;
 generate for(g=0;g<CORES;g=g+1) begin:stim
  reg qu=0,qb=1,bitv=0;integer runs=0;
  initial begin force dut.gen_core[g].u_engine.u_core.qu_w=qu;force dut.gen_core[g].u_engine.u_core.qb_w=qb;end
  always @(clear_ev) runs=0;
  always @(posedge dut.gen_core[g].u_engine.excite) begin
   bitv=expected_word[g]^((g%5==0)&&(cur_votes>=3)&&((runs==0)||((runs==cur_votes-1)&&(cur_votes>=5))));
   runs=runs+1;
   qu=~bitv;qb=1;#2;qb=0;#2;qb=1;
  end
  always @(posedge dut.gen_core[g].u_engine.latch) begin
   qu=bitv;qb=1;#2;qb=0;#2;qb=1;
  end
 end endgenerate

 always @(negedge clk) if(dut.state==1) begin
  busy_count=0;for(h=0;h<CORES;h=h+1) if(dut.busy[h]) busy_count=busy_count+1;
  if(dut.control[0] && busy_count>1) $fatal(1,"Sequential mode overlapped cores");
  if(!dut.control[0] && busy_count==CORES) saw_parallel=1;
 end

 task put(input [7:0] b);
 integer i;begin @(negedge clk);uart_rx=0;#80;for(i=0;i<8;i=i+1) begin uart_rx=b[i];#80;end uart_rx=1;#80;end
 endtask
 task get(output [7:0] b);
 integer i;begin @(negedge uart_tx);#120;for(i=0;i<8;i=i+1) begin b[i]=uart_tx;#80;end if(uart_tx!==1) $fatal(1,"Stop bit");end
 endtask

 reg [7:0] reply[0:REP-1];reg [7:0] check;integer j,m;
 reg [63:0] maj,una;reg [15:0] xr;reg [9:0] exp_xor;reg [59:0] exp_una;
 task query(input [479:0] c,input [7:0] control,input [7:0] votes,input accepted);
 begin
  ->clear_ev;cur_votes=votes;
  check=8'ha7^control^votes;put(8'ha7);put(control);put(votes);
  for(j=0;j<CORES;j=j+1) begin put(c[j*8+:8]);check=check^c[j*8+:8];end put(check);
  for(j=0;j<REP;j=j+1) get(reply[j]);
  check=0;for(j=0;j<REP-1;j=j+1) check=check^reply[j];
  if(reply[0]!==8'hd7 || reply[1]!==control || reply[2]!==votes || reply[REP-1]!==check) $fatal(1,"Frame/checksum");
  if(reply[63] !== (accepted?8'h71:8'h70)) $fatal(1,"Status %h",reply[63]);
  if(accepted) begin
   for(j=0;j<CORES;j=j+1) if(reply[j+3]!==c[j*8+:8]) $fatal(1,"Configuration readback core %0d",j);
   for(j=0;j<8;j=j+1) begin maj[8*j+:8]=reply[64+j];una[8*j+:8]=reply[72+j];end
   xr={reply[81],reply[80]};
   for(m=0;m<GROUPS;m=m+1) exp_xor[m]=^expected_word[m*GSIZE+:GSIZE];
   for(m=0;m<CORES;m=m+1) exp_una[m]=!((m%5==0)&&(votes>=3));
   if(EXPOSE) begin
    if(maj[59:0]!==expected_word || maj[63:60]!==0) $fatal(1,"Majority word %h",maj);
    if(una[59:0]!==exp_una || una[63:60]!==0) $fatal(1,"Unanimity word %h",una);
   end else if(maj!==0 || una!==0) $fatal(1,"Deployment build leaked per-core bits");
   if(xr[9:0]!==exp_xor || xr[15:10]!==0) $fatal(1,"Group XOR %h expected %h",xr,exp_xor);
  end
  #300;
 end endtask

 reg [479:0] configs,flipped;integer c;
 initial begin
  for(c=0;c<CORES;c=c+1) begin
   configs[c*8+:8]=(c*8'h9d)^8'h5a;
   if (!(^configs[c*8+:8])) configs[c*8]=~configs[c*8];
  end
  for(c=0;c<CORES;c=c+1) flipped[c*8+:8]=~configs[c*8+:8];   // 8-bit complement keeps odd parity
  #400;
  query(configs,16,5,1);                       // parallel, 5 votes
  if(!saw_parallel) $fatal(1,"Parallel mode not exercised");
  expected_word=~expected_word;
  query(flipped,17,3,1);                       // sequential, 3 votes
  query(configs,2,1,1);                        // 1 vote: always unanimous
  query(configs,254,7,1);                      // longest excite wait
  query(configs,16,63,1);                      // maximum votes
  query(configs,0,5,0);                        // zero excite wait rejected
  query(configs,16,0,0);                       // zero votes rejected
  query(configs,16,64,0);                      // too many votes rejected
  configs[8]=~configs[8];                      // core 1 now has even parity
  query(configs,16,5,0);
  configs[8]=~configs[8];
  put(8'ha7);put(16);put(5);for(j=0;j<CORES;j=j+1) put(0);put(0);#4000;   // bad checksum
  if(dut.state!==0) $fatal(1,"Bad checksum launched");
  put(8'ha7);put(16);#4000;if(dut.parser!==0) $fatal(1,"Truncated recovery");
  query(configs,3,5,1);
  $display("PASS (EXPOSE_CORE_BITS=%0d): Latch-controlled capture, on-chip majority vote and unanimity flags, 10-group XOR, 60-core configuration readback, parallel/sequential activation, request rejection, checksums and recovery",EXPOSE);$finish;
 end
 initial begin #60000000; $fatal(1,"Watchdog");end
endmodule
