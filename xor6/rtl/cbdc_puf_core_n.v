`timescale 1ns/1ps
`default_nettype none
//==============================================================================
// Module: cbdc_puf_core_n
// Description:
//   Same CBDC cell as ../rtl/cbdc_puf_core.v (Figure 1 interpretation: fixed AND
//   entrance gates, two cross-coupled configurable chains, one negative-edge
//   response FF enabled by Latch), with the number of stages as a parameter.
//   The XOR-6 variant uses N_STAGES = 8.
//
//   Instance names (u_chain_upper, u_chain_lower, u_arbiter_dff) are kept
//   identical to the 16-stage core so the placement/routing/audit scripts can
//   address the same hierarchy.
//
//   Response convention (unchanged): the FF samples Qu (D) on the falling edge
//   of Qb (inverted clock), so Q = 1 means the upper chain was slower.
//   Fixed AND entrance gates require odd-parity configurations; the controller
//   rejects even-parity configurations.
//==============================================================================
module cbdc_puf_core_n #(
    parameter integer N_STAGES = 8
) (
    input  wire [N_STAGES-1:0] c,
    input  wire                excite,
    input  wire                latch,
    input  wire                clr,
    output wire                q
);
    // synthesis translate_off
    initial if (N_STAGES < 1) $fatal(1, "N_STAGES must be positive");
    // synthesis translate_on

    (* DONT_TOUCH="TRUE" *) wire qu_w, qb_w;

    (* DONT_TOUCH="TRUE" *)
    cbdc_puf_chain #(.N_STAGES(N_STAGES), .GATE_INIT(4'h8), .AUTO_PARITY(0), .ELEMENT_STYLE(0))
    u_chain_upper (.excite_i(excite), .feedback_i(qb_w), .c_i(c), .chain_o(qu_w));

    (* DONT_TOUCH="TRUE" *)
    cbdc_puf_chain #(.N_STAGES(N_STAGES), .GATE_INIT(4'h8), .AUTO_PARITY(0), .ELEMENT_STYLE(0))
    u_chain_lower (.excite_i(excite), .feedback_i(qu_w), .c_i(c), .chain_o(qb_w));

    (* DONT_TOUCH="TRUE" *)
    FDCE_1 #(.INIT(1'b0)) u_arbiter_dff (.Q(q), .C(qb_w), .CE(latch), .CLR(clr), .D(qu_w));
endmodule
`default_nettype wire
