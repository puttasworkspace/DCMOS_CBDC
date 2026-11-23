`timescale 1ns/1ps
`default_nettype none
//==============================================================================
// Module: cbdc_vote_engine
// Description:
//   One CBDC core plus its run controller, repeated VOTES times per request
//   with an on-chip majority vote.
//
//   - start         : one-cycle pulse, accepted only while idle
//   - challenge     : N_STAGES-bit configuration (must have odd parity)
//   - votes         : number of runs (1..63). Use an odd number so there are
//                     no ties; with an even number a tie counts as 0.
//   - majority      : 1 if more than half of the runs returned 1
//   - unanimous     : 1 if every run agreed (useful as a stability flag)
//   - ones          : number of runs that returned 1 (for reliability studies)
//   - valid / error : one-cycle pulses; error = unsupported request
//                     (even parity, zero excite wait, or votes = 0)
//
//   Hierarchy (u_ctrl, u_core) matches ../rtl/cbdc_serial_engine.v so the
//   placement and audit scripts find gen_core[i].u_engine/u_core/... and
//   gen_core[i].u_engine/u_ctrl/puf_excite_o_reg exactly as before.
//==============================================================================
module cbdc_vote_engine #(
    parameter integer N_STAGES = 8
) (
    input  wire                clk,
    input  wire                reset,
    input  wire                start,
    input  wire [N_STAGES-1:0] challenge,
    input  wire [7:0]          excite_cycles,
    input  wire [5:0]          votes,
    output reg                 valid     = 1'b0,
    output reg                 error     = 1'b0,
    output reg                 majority  = 1'b0,
    output reg                 unanimous = 1'b0,
    output reg  [5:0]          ones      = 6'd0,
    output wire                busy,
    output wire [N_STAGES-1:0] configuration
);
    wire excite, latch, clr, q;
    wire ctrl_valid, ctrl_error, ctrl_busy, ctrl_bit;

    reg                ctrl_start = 1'b0;
    reg                active     = 1'b0;
    reg [5:0]          target     = 6'd0;
    reg [5:0]          done_runs  = 6'd0;
    reg [5:0]          ones_r     = 6'd0;
    reg [N_STAGES-1:0] held       = {N_STAGES{1'b0}};

    cbdc_puf_ctrl #(
        .N_STAGES(N_STAGES), .AUTO_PARITY(0), .GATE_INIT(4'h8)
    ) u_ctrl (
        .clk(clk), .rst_n(~reset), .start_i(ctrl_start), .challenge_i(held),
        .excite_cycles_i(excite_cycles),
        .busy_o(ctrl_busy), .resp_valid_o(ctrl_valid), .resp_bit_o(ctrl_bit),
        .request_error_o(ctrl_error),
        .puf_c_o(configuration), .puf_excite_o(excite), .puf_latch_o(latch),
        .puf_clr_o(clr), .puf_q_i(q)
    );

    cbdc_puf_core_n #(.N_STAGES(N_STAGES)) u_core (
        .c(configuration), .excite(excite), .latch(latch), .clr(clr), .q(q)
    );

    assign busy = active | ctrl_busy;

    // Count including the run that has just finished.
    wire [6:0] ones_now = {1'b0, ones_r} + {6'd0, ctrl_bit};

    always @(posedge clk) begin
        if (reset) begin
            valid <= 1'b0; error <= 1'b0; majority <= 1'b0; unanimous <= 1'b0; ones <= 6'd0;
            ctrl_start <= 1'b0; active <= 1'b0; target <= 6'd0; done_runs <= 6'd0;
            ones_r <= 6'd0; held <= {N_STAGES{1'b0}};
        end else begin
            valid <= 1'b0;
            error <= 1'b0;
            ctrl_start <= 1'b0;
            if (!active) begin
                if (start) begin
                    if (votes == 6'd0) begin
                        error <= 1'b1;
                    end else begin
                        active     <= 1'b1;
                        held       <= challenge;   // seen by u_ctrl on the next cycle
                        target     <= votes;
                        done_runs  <= 6'd0;
                        ones_r     <= 6'd0;
                        ctrl_start <= 1'b1;
                    end
                end
            end else if (ctrl_error) begin
                active <= 1'b0;
                error  <= 1'b1;
            end else if (ctrl_valid) begin
                if (done_runs + 6'd1 == target) begin
                    active    <= 1'b0;
                    valid     <= 1'b1;
                    ones      <= ones_now[5:0];
                    majority  <= ({ones_now, 1'b0} > {2'b00, target});   // 2*ones > votes
                    unanimous <= (ones_now == 7'd0) || (ones_now == {1'b0, target});
                end else begin
                    done_runs  <= done_runs + 6'd1;
                    ones_r     <= ones_now[5:0];
                    ctrl_start <= 1'b1;   // u_ctrl is idle again in this cycle
                end
            end
        end
    end
endmodule
`default_nettype wire
