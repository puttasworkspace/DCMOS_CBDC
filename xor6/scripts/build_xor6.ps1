# Build the XOR-6 bitstream (60 cores x 8 stages) in an isolated stage folder.
#
#   powershell -ExecutionPolicy Bypass -File xor6\scripts\build_xor6.ps1
#   powershell -ExecutionPolicy Bypass -File xor6\scripts\build_xor6.ps1 -PrepareOnly
#   powershell -ExecutionPolicy Bypass -File xor6\scripts\build_xor6.ps1 -ResumeStage xor6\rebuilds\run_<id>
#
# Steps: simulate (Icarus) -> synthesize -> constrained placement -> fixed
# routing -> route refinement -> structural audit -> 4-shard delay audit ->
# paired-route acceptance -> DRC/timing checks -> bitstream -> build record.
# -HideCoreBits builds the deployment variant (only XOR bits leave the chip).
# Nothing in the original 16-stage design, layout or bitstream is modified.
param(
 [string]$VivadoPath='C:\AMDDesignTools\2025.2\Vivado\bin\vivado.bat',
 [string]$IcarusBin='C:\iverilog\bin',
 [string]$Python='',
 [switch]$PrepareOnly,
 [switch]$SkipSimulation,
 [switch]$HideCoreBits,
 [string]$ResumeStage=''
)
$ErrorActionPreference='Stop'
$xor6=Split-Path $PSScriptRoot -Parent
$root=Split-Path $xor6 -Parent
if(!$Python){$Python=Join-Path $root 'runtime/python/python.exe'}
if(!(Test-Path $Python)){$Python='python'}

if($ResumeStage){
 # Resume = keep placement and initial routing (build/routed.dcp), take the
 # CURRENT xor6/scripts/build/refine_routes.tcl, redo the refinement and audits.
 $stage=(Resolve-Path -LiteralPath $ResumeStage).Path
 if(!(Test-Path (Join-Path $stage 'build/routed.dcp'))){throw 'Resume needs a stage with build/routed.dcp'}
 Copy-Item (Join-Path $xor6 'scripts/build/refine_routes.tcl') (Join-Path $stage 'scripts') -Force
@'
set root [file normalize [pwd]]
open_checkpoint $root/build/routed.dcp
source $root/scripts/refine_routes.tcl
puts "XOR6_ROUTE_COMPLETE"
'@ | Set-Content (Join-Path $stage 'resume_xor6.tcl')
 Remove-Item -Recurse -Force (Join-Path $stage 'build/audit') -ErrorAction SilentlyContinue
}else{
 $stage=Join-Path $xor6 ('rebuilds/run_'+[Guid]::NewGuid().ToString('N'))
 New-Item -ItemType Directory -Force -Path (Join-Path $stage 'rtl'),(Join-Path $stage 'scripts'),(Join-Path $stage 'build') | Out-Null
 foreach($n in @('cbdc_puf_element.v','cbdc_puf_chain.v','cbdc_puf_ctrl.v','cbdc_uart.v','cbdc_button.v')){Copy-Item (Join-Path $root ('rtl/'+$n)) (Join-Path $stage 'rtl')}
 Get-ChildItem (Join-Path $xor6 'rtl') -Filter *.v | Copy-Item -Destination (Join-Path $stage 'rtl')
 Get-ChildItem (Join-Path $xor6 'scripts/build') -File | Copy-Item -Destination (Join-Path $stage 'scripts')
 if($HideCoreBits){Add-Content (Join-Path $stage 'scripts/params.tcl') 'set EXPOSE_CORE_BITS 0'}
 Copy-Item (Join-Path $xor6 'constraints/basys3_xor6.xdc') (Join-Path $stage 'basys3_xor6.xdc')
 Copy-Item (Join-Path $xor6 'layout/layout.tcl') (Join-Path $stage 'layout.tcl')
 Copy-Item (Join-Path $xor6 'layout/layout.json') (Join-Path $stage 'layout.json')
 Copy-Item (Join-Path $xor6 'layout/internal_route_template8.tcl') (Join-Path $stage 'internal_route_template.tcl')
 $hashes=[ordered]@{}
 foreach($f in Get-ChildItem $stage -Recurse -File){$hashes[$f.FullName.Substring($stage.Length+1).Replace('\','/')]=(Get-FileHash $f.FullName).Hash}
 $hashes | ConvertTo-Json | Set-Content (Join-Path $stage 'STAGE_INPUTS.json')
@'
set root [file normalize [pwd]]
source $root/scripts/synthesize.tcl
close_project
source $root/scripts/implement.tcl
source $root/scripts/refine_routes.tcl
puts "XOR6_ROUTE_COMPLETE"
'@ | Set-Content (Join-Path $stage 'implement_xor6.tcl')
 Write-Output ('Prepared isolated XOR-6 build: '+$stage)
 if($PrepareOnly){return}
 if(!$SkipSimulation){
  & $Python -B (Join-Path $xor6 'sim/run_sim.py') --icarus-bin $IcarusBin --log-dir (Join-Path $stage 'sim_logs')
  if($LASTEXITCODE -ne 0){throw 'Simulation failed; build stopped'}
 }
}
if(!(Test-Path -LiteralPath $VivadoPath)){throw 'Vivado not found; pass -VivadoPath'}
Push-Location $stage
try{
 if($ResumeStage){
  & $VivadoPath -mode batch -notrace -nojournal -log resume.log -source resume_xor6.tcl *> resume_console.txt
  if($LASTEXITCODE -ne 0){throw 'Route refinement failed; see resume.log in the stage folder'}
 }else{
  & $VivadoPath -mode batch -notrace -nojournal -log implementation.log -source implement_xor6.tcl *> implementation_console.txt
  if($LASTEXITCODE -ne 0){throw 'Implementation failed; see implementation.log in the stage folder'}
 }
 $jobs=@(for($i=0;$i -lt 4;$i++){
  Start-Job -ArgumentList $stage,$VivadoPath,$i -ScriptBlock {
   param($s,$v,$n)
   Set-Location $s
   & $v -mode batch -notrace -nojournal -log ('audit_'+$n+'.log') -source scripts/review_shard.tcl -tclargs $n *> ('audit_console_'+$n+'.txt')
   if($LASTEXITCODE -ne 0){throw ('Delay audit failed: '+$n)}
  }
 })
 $jobs | Wait-Job | Out-Null
 foreach($j in $jobs){if($j.State -ne 'Completed'){Receive-Job $j;throw 'Delay audit job failed'}}
 & $Python -B scripts/summarize_routes.py
 if($LASTEXITCODE -ne 0){throw ('Paired-route matching not accepted; see build/route_summary.json. Extend xor6/scripts/build/refine_routes.tcl for the listed stage/kind, then rerun with -ResumeStage '+$stage)}
 & $VivadoPath -mode batch -notrace -nojournal -log finalize.log -source scripts/finalize.tcl *> finalize_console.txt
 if($LASTEXITCODE -ne 0){throw 'Finalization failed (DRC/timing/structure); see finalize.log'}
 & $Python -B scripts/record_build.py
 if($LASTEXITCODE -ne 0){throw 'Build record failed'}
 Write-Output ('XOR6_BUILD_COMPLETE '+(Join-Path $stage 'build/xor6_array60.bit'))
}finally{Pop-Location}
