`timescale 1ns/1ps
`default_nettype none
//==============================================================================
// Module: cbdc_xor6_serial   (top level, Basys 3 / xc7a35t)
//
// 60 CBDC cores with 8 stages each, arranged as 10 groups of 6 cores.
// Every core is run VOTES times and majority-voted on chip; the 6 voted bits of
// a group are XORed into one response bit. One request -> 10 XOR response bits.
//
// Core index k = group*6 + member (group 0..9, member 0..5).
//
// UART 115200 8N1 (100 MHz / UART_CLKS). All checksums are XOR of every
// preceding byte in the frame (same scheme as the 64-core design).
//
// Request (64 bytes):
//   [0]        A7                header
//   [1]        control           bit0 = sequential diagnostic mode (one core
//                                at a time); bits7:1 = excite wait in 100 MHz
//                                cycles (1..127)
//   [2]        votes             runs per core, 1..63 (odd recommended)
//   [3..62]    config[k]         one byte per core, k = 0..59, ODD parity
//   [63]       checksum
//
// Reply (83 bytes):
//   [0]        D7                header
//   [1]        control           echo
//   [2]        votes             echo
//   [3..62]    config[k]         configuration actually latched by each core
//   [63]       flags             71 = completed, 70 = rejected (bad control,
//                                votes or parity), E0 = timeout / error
//   [64..71]   majority[63:0]    voted bit per core, LSB first (bits 60..63 = 0)
//   [72..79]   unanimous[63:0]   1 = all runs of that core agreed
//   [80..81]   xor[15:0]         group response bits, LSB first (bits 10..15 = 0)
//   [82]       checksum
//
// EXPOSE_CORE_BITS = 0 zeroes the per-core majority/unanimous bytes so only the
// XOR responses leave the chip (deployment mode). Keep 1 for characterisation.
//==============================================================================
module cbdc_xor6_serial #(
    parameter integer UART_CLKS        = 868,
    parameter integer N_STAGES         = 8,
    parameter integer GROUPS           = 10,
    parameter integer GROUP_SIZE       = 6,
    parameter integer EXPOSE_CORE_BITS = 1,
    parameter integer TIMEOUT_CYCLES   = 4000000
) (
    input  wire        clk,
    input  wire        btnU,
    input  wire        uart_rx,
    output wire        uart_tx,
    output wire [15:0] led
);
    localparam integer CORE_COUNT     = GROUPS * GROUP_SIZE;     // 60
    localparam integer WORD_BYTES     = (CORE_COUNT + 7) / 8;    // 8
    localparam integer XOR_BYTES      = (GROUPS + 7) / 8;        // 2
    localparam integer REQ_LAST       = 3 + CORE_COUNT;          // checksum index (63)
    localparam integer CFG_BEGIN      = 3;
    localparam integer FLAGS_INDEX    = 3 + CORE_COUNT;          // 63
    localparam integer MAJ_BEGIN      = FLAGS_INDEX + 1;         // 64
    localparam integer UNA_BEGIN      = MAJ_BEGIN + WORD_BYTES;  // 72
    localparam integer XOR_BEGIN      = UNA_BEGIN + WORD_BYTES;  // 80
    localparam integer REPLY_BYTES    = XOR_BEGIN + XOR_BYTES + 1; // 83
    localparam integer INDEX_WIDTH    = $clog2(REPLY_BYTES + 1);
    localparam integer CORE_WIDTH     = $clog2(CORE_COUNT);

    // synthesis translate_off
    initial begin
        if (N_STAGES != 8) $fatal(1, "This protocol carries one configuration byte per core: N_STAGES must be 8");
        if (CORE_COUNT < 2 || CORE_COUNT > 64) $fatal(1, "CORE_COUNT must be 2..64");
    end
    // synthesis translate_on

    //--------------------------------------------------------------------------
    // Reset and UART (identical to the 64-core design)
    //--------------------------------------------------------------------------
    reg  [4:0] por = 5'd0;
    wire pr = ~por[4];
    always @(posedge clk) if (pr) por <= por + 5'd1;

    wire button;
    cbdc_button u_reset (.clk(clk), .reset(pr), .raw_i(btnU), .level_o(button));
    wire reset = pr | button;

    wire [7:0] rd;
    wire received, framing, tx_busy;
    reg        send = 1'b0;
    reg  [7:0] td   = 8'd0;
    cbdc_uart #(.CLKS(UART_CLKS)) uart (
        .clk(clk), .reset(reset), .rx(uart_rx), .send(send), .tx_data(td), .tx(uart_tx),
        .busy(tx_busy), .rx_data(rd), .received(received), .framing_error(framing)
    );

    //--------------------------------------------------------------------------
    // State
    //--------------------------------------------------------------------------
    reg [1:0]               state = 2'd0;      // 0 receive, 1 run, 2 reply
    reg [INDEX_WIDTH-1:0]   parser = 0, index = 0;
    reg [8*CORE_COUNT-1:0]  challenge = 0;
    reg [7:0]               control = 8'd0, votes = 8'd0, crc = 8'd0, txcrc = 8'd0, flags = 8'd0;
    reg [CORE_COUNT-1:0]    start = 0, done_mask = 0, result = 0, agree = 0;
    reg [CORE_WIDTH-1:0]    active_core = 0;
    reg [31:0]              timeout = 32'd0, partial_timeout = 32'd0;

    wire [CORE_COUNT-1:0]   valid, error, busy, majority, unanimous, parity;
    wire [8*CORE_COUNT-1:0] configuration;

    genvar g;
    generate
        for (g = 0; g < CORE_COUNT; g = g + 1) begin : gen_core
            assign parity[g] = ^challenge[g*8 +: 8];
            cbdc_vote_engine #(.N_STAGES(N_STAGES)) u_engine (
                .clk(clk), .reset(reset), .start(start[g]),
                .challenge(challenge[g*8 +: 8]),
                .excite_cycles({1'b0, control[7:1]}),
                .votes(votes[5:0]),
                .valid(valid[g]), .error(error[g]), .majority(majority[g]),
                .unanimous(unanimous[g]), .ones(), .busy(busy[g]),
                .configuration(configuration[g*8 +: 8])
            );
        end
    endgenerate

    // Group XOR of the voted bits.
    wire [GROUPS-1:0] xor_bits;
    generate
        for (g = 0; g < GROUPS; g = g + 1) begin : gen_group
            assign xor_bits[g] = ^result[g*GROUP_SIZE +: GROUP_SIZE];
        end
    endgenerate

    wire [8*WORD_BYTES-1:0] maj_pad = {{(8*WORD_BYTES-CORE_COUNT){1'b0}}, result};
    wire [8*WORD_BYTES-1:0] una_pad = {{(8*WORD_BYTES-CORE_COUNT){1'b0}}, agree};
    wire [8*XOR_BYTES-1:0]  xor_pad = {{(8*XOR_BYTES-GROUPS){1'b0}}, xor_bits};

    wire request_ok = (control[7:1] != 7'd0) && (votes != 8'd0) && (votes <= 8'd63) && (&parity);

    //--------------------------------------------------------------------------
    // Reply byte at position `index` (checksum handled separately)
    //--------------------------------------------------------------------------
    reg [7:0] reply_byte;
    always @(*) begin
        reply_byte = 8'd0;
        if (index == 0)                         reply_byte = 8'hD7;
        else if (index == 1)                    reply_byte = control;
        else if (index == 2)                    reply_byte = votes;
        else if (index < FLAGS_INDEX)           reply_byte = configuration[(index-CFG_BEGIN)*8 +: 8];
        else if (index == FLAGS_INDEX)          reply_byte = flags;
        else if (index < UNA_BEGIN)             reply_byte = EXPOSE_CORE_BITS ? maj_pad[(index-MAJ_BEGIN)*8 +: 8] : 8'd0;
        else if (index < XOR_BEGIN)             reply_byte = EXPOSE_CORE_BITS ? una_pad[(index-UNA_BEGIN)*8 +: 8] : 8'd0;
        else if (index < REPLY_BYTES - 1)       reply_byte = xor_pad[(index-XOR_BEGIN)*8 +: 8];
    end

    assign led = {4'b0, 1'b1, (|busy), state == 2'd2, state == 2'd0, xor_bits[7:0]};

    integer k;
    always @(posedge clk) begin
        if (reset) begin
            state <= 2'd0; parser <= 0; index <= 0; challenge <= 0; control <= 8'd0; votes <= 8'd0;
            crc <= 8'd0; txcrc <= 8'd0; flags <= 8'd0; start <= 0; done_mask <= 0; result <= 0;
            agree <= 0; active_core <= 0; timeout <= 32'd0; partial_timeout <= 32'd0;
            send <= 1'b0; td <= 8'd0;
        end else begin
            start <= 0;
            send  <= 1'b0;
            case (state)
            //------------------------------------------------------------------
            2'd0: begin   // receive request
                if (parser != 0) begin
                    if (partial_timeout == UART_CLKS*40) begin parser <= 0; partial_timeout <= 32'd0; end
                    else partial_timeout <= partial_timeout + 32'd1;
                end
                if (framing) parser <= 0;
                else if (received) begin
                    partial_timeout <= 32'd0;
                    if (parser == 0) begin
                        if (rd == 8'hA7) begin parser <= 1; crc <= 8'hA7; end
                    end else if (parser == 1) begin
                        control <= rd; crc <= crc ^ rd; parser <= 2;
                    end else if (parser == 2) begin
                        votes <= rd; crc <= crc ^ rd; parser <= 3;
                    end else if (parser < REQ_LAST) begin
                        challenge[(parser-CFG_BEGIN)*8 +: 8] <= rd; crc <= crc ^ rd; parser <= parser + 1;
                    end else begin
                        parser <= 0;
                        if (rd == crc) begin
                            done_mask <= 0; result <= 0; agree <= 0; timeout <= 32'd0; active_core <= 0;
                            if (request_ok) begin
                                start <= control[0] ? {{(CORE_COUNT-1){1'b0}}, 1'b1} : {CORE_COUNT{1'b1}};
                                state <= 2'd1;
                            end else begin
                                flags <= 8'h70; state <= 2'd2; index <= 0; txcrc <= 8'd0;
                            end
                        end
                    end
                end
            end
            //------------------------------------------------------------------
            2'd1: begin   // run all cores (parallel) or one after another (sequential)
                timeout <= timeout + 32'd1;
                for (k = 0; k < CORE_COUNT; k = k + 1)
                    if (valid[k]) begin done_mask[k] <= 1'b1; result[k] <= majority[k]; agree[k] <= unanimous[k]; end
                if (control[0] && valid[active_core] && active_core < CORE_COUNT-1) begin
                    active_core <= active_core + 1'b1;
                    start <= {{(CORE_COUNT-1){1'b0}}, 1'b1} << (active_core + 1'b1);
                end
                if (&done_mask) begin
                    flags <= 8'h71; state <= 2'd2; index <= 0; txcrc <= 8'd0;
                end else if ((|error) || timeout == TIMEOUT_CYCLES) begin
                    flags <= 8'hE0; state <= 2'd2; index <= 0; txcrc <= 8'd0;
                end
            end
            //------------------------------------------------------------------
            2'd2: begin   // transmit reply
                if (!tx_busy && !send) begin
                    if (index == REPLY_BYTES) begin
                        state <= 2'd0; index <= 0;
                    end else begin
                        if (index == REPLY_BYTES-1) td <= txcrc;
                        else begin td <= reply_byte; txcrc <= txcrc ^ reply_byte; end
                        send  <= 1'b1;
                        index <= index + 1'b1;
                    end
                end
            end
            default: state <= 2'd0;
            endcase
        end
    end
endmodule
`default_nettype wire
