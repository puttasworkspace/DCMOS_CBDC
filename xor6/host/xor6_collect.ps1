# PowerShell twin of xor6_collect.py (no pyserial needed; uses .NET SerialPort).
# Replays an xor6 matrix (from xor6_configs.py or xor6_keygen.py matrix) on the
# board and writes the same CSV + .metadata.json as the Python collector.
#
#   powershell -ExecutionPolicy Bypass -File xor6\host\xor6_collect.ps1 -Port COM5 -Matrix matrix.json -Output run.csv -Trials 3 -Votes 21
param(
 [Parameter(Mandatory=$true)][string]$Port,
 [Parameter(Mandatory=$true)][string]$Matrix,
 [Parameter(Mandatory=$true)][string]$Output,
 [ValidateRange(1,1000)][int]$Trials=1,
 [ValidateRange(1,63)][int]$Votes=21,
 [ValidateRange(1,127)][int]$ExciteCycles=8,
 [switch]$Sequential,
 [string]$BuildRecord=''
)
$ErrorActionPreference='Stop'
$Output=[IO.Path]::GetFullPath($Output)
foreach($p in @($Output,($Output+'.metadata.json'))){if(Test-Path -LiteralPath $p){throw "Output exists: $p"}}
New-Item -ItemType Directory -Force (Split-Path $Output -Parent) | Out-Null
$Matrix=(Resolve-Path -LiteralPath $Matrix).Path
$m=Get-Content -LiteralPath $Matrix -Raw | ConvertFrom-Json
if($m.format -ne 'xor6-matrix-v1'){throw 'Not an xor6 matrix file'}
$patterns=@($m.patterns)
$mode=$(if($Sequential){'Sequential'}else{'Parallel'})
$control=($ExciteCycles -shl 1) -bor $(if($Sequential){1}else{0})

function Get-Hex([byte[]]$b,[int]$offset,[int]$count){($b[$offset..($offset+$count-1)] | ForEach-Object {$_.ToString('X2')}) -join ''}

$serial=[IO.Ports.SerialPort]::new($Port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One)
$serial.ReadTimeout=2000;$serial.WriteTimeout=2000;$serial.DtrEnable=$false;$serial.RtsEnable=$false
$writer=$null;$queries=0;$start=Get-Date
try{
 $serial.Open();Start-Sleep -Milliseconds 100;$serial.DiscardInBuffer()
 $writer=[IO.StreamWriter]::new($Output,$false)
 $writer.WriteLine('utc,pattern,trial,challenge_hex,configs_hex,flags_hex,votes,excite_cycles,mode,majority_hex,unanimous_hex,xor_hex')
 foreach($row in $patterns){
  $cfg=@($row.configs)
  if($cfg.Count -ne 60){throw "Pattern $($row.pattern): need 60 configurations"}
  $req=New-Object byte[] 64;$req[0]=0xA7;$req[1]=$control;$req[2]=$Votes
  for($k=0;$k -lt 60;$k++){
   $v=[int]$cfg[$k];$par=0;for($b=0;$b -lt 8;$b++){$par=$par -bxor (($v -shr $b) -band 1)}
   if($v -lt 0 -or $v -gt 255 -or $par -ne 1){throw "Pattern $($row.pattern) core ${k}: configuration must be an odd-parity byte"}
   $req[3+$k]=$v
  }
  $crc=0;for($i=0;$i -lt 63;$i++){$crc=$crc -bxor $req[$i]};$req[63]=$crc
  for($trial=1;$trial -le $Trials;$trial++){
   $serial.Write($req,0,64);$rep=New-Object byte[] 83
   for($i=0;$i -lt 83;$i++){$rep[$i]=[byte]$serial.ReadByte()}
   $crc=0;for($i=0;$i -lt 82;$i++){$crc=$crc -bxor $rep[$i]}
   if($rep[0] -ne 0xD7 -or $rep[82] -ne $crc -or $rep[1] -ne $control -or $rep[2] -ne $Votes){throw 'Invalid reply frame: is the XOR-6 bitstream loaded?'}
   if($rep[63] -ne 0x71){throw ('Board returned flags {0:X2} at pattern {1}' -f $rep[63],$row.pattern)}
   for($k=0;$k -lt 60;$k++){if($rep[3+$k] -ne $req[3+$k]){throw 'Latched configuration differs from request'}}
   $maj=[BitConverter]::ToUInt64($rep,64) -band 0x0FFFFFFFFFFFFFFF
   $una=[BitConverter]::ToUInt64($rep,72) -band 0x0FFFFFFFFFFFFFFF
   $xr=[BitConverter]::ToUInt16($rep,80) -band 0x3FF
   $writer.WriteLine(('{0},{1},{2},{3},{4},71,{5},{6},{7},{8},{9},{10}' -f [DateTime]::UtcNow.ToString('o'),$row.pattern,$trial,$row.challenge_hex,(Get-Hex $rep 3 60),$Votes,$ExciteCycles,$mode,$maj.ToString('X15'),$una.ToString('X15'),$xr.ToString('X3')))
   $queries++
  }
  if(($row.pattern % 500) -eq 499){$writer.Flush();Write-Output ("{0} patterns, {1} queries, {2:N0} s" -f ($row.pattern+1),$queries,((Get-Date)-$start).TotalSeconds)}
 }
}finally{if($writer){$writer.Dispose()};if($serial.IsOpen){$serial.Close()};$serial.Dispose()}
$meta=[ordered]@{utc=[DateTime]::UtcNow.ToString('o');variant='xor6_array60_8stage';matrix=$Matrix;
 matrix_sha256=(Get-FileHash -LiteralPath $Matrix -Algorithm SHA256).Hash;matrix_mode=$m.mode;patterns=$patterns.Count;
 trials=$Trials;votes=$Votes;excite_cycles=$ExciteCycles;mode=$mode;source="board on $Port";queries=$queries}
if($BuildRecord){$rec=Get-Content -LiteralPath $BuildRecord -Raw | ConvertFrom-Json;$meta.bitstream_sha256=$rec.sha256;$meta.bitstream_variant=$rec.variant}
$meta | ConvertTo-Json | Set-Content -LiteralPath ($Output+'.metadata.json')
Write-Output "Saved $queries queries to $Output"
