`timescale 1ns/1ps
// Exhaustive logic check of one 8-stage chain (all 256 configurations):
// with Excite=0 the chain output equals the configuration parity, and with
// Excite=1/feedback=1 it equals the inverted parity (buffer/inverter composition).
module tb_chain8_truth;
 reg excite=0,feedback=0;reg [7:0] c=0;wire q;integer k;
 cbdc_puf_chain #(.N_STAGES(8),.GATE_INIT(4'h8),.AUTO_PARITY(0),.ELEMENT_STYLE(0)) chain(.excite_i(excite),.feedback_i(feedback),.c_i(c),.chain_o(q));
 initial begin
  for(k=0;k<256;k=k+1) begin
   c=k;excite=0;feedback=0;#4;if(q!==(^(c))) $fatal(1,"Initialization parity");
   excite=1;feedback=1;#4;if(q!==~(^c)) $fatal(1,"Buffer/inverter truth");
  end
  $display("PASS: all 256 8-stage configurations match fixed-AND initialization parity and buffer/inverter composition");$finish;
 end
endmodule
