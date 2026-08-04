$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$repo = "C:\Users\Abhishek.Jasani\OneDrive - Sorigin Group\Project\cursor_teams\docs\mockups"
$srcHtml = Get-Content (Join-Path $repo "ui-overview.html") -Raw -Encoding UTF8
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$tmp = $env:TEMP

$names = @{ 1 = "screen-1-office"; 2 = "screen-2-floor"; 3 = "screen-3-box"; 4 = "screen-4-models" }

foreach ($n in 1..4) {
    # show only screen N, hide page title
    $override = "<style>h1,.sub{display:none!important}.page>.screen{display:none!important}.page>.screen:nth-of-type($n){display:block!important}body{padding:24px 16px}</style></head>"
    $html = $srcHtml -replace "</head>", $override
    $tmpHtml = Join-Path $tmp "shot-$n.html"
    Set-Content -Path $tmpHtml -Value $html -Encoding UTF8

    $tmpPng = Join-Path $tmp "shot-$n.png"
    if (Test-Path $tmpPng) { Remove-Item $tmpPng -Force }
    $chromeArgs = @(
        "--headless=new", "--disable-gpu",
        "--user-data-dir=$tmp\chrome-shot",
        "--window-size=1400,2000",
        "--screenshot=$tmpPng",
        "file:///$($tmpHtml -replace '\\','/')"
    )
    Start-Process -FilePath $chrome -ArgumentList $chromeArgs -Wait -WindowStyle Hidden
    if (-not (Test-Path $tmpPng)) { throw "screenshot $n failed" }

    # auto-crop trailing blank rows (background #0d1117)
    $bmp = New-Object System.Drawing.Bitmap($tmpPng)
    $bg = $bmp.GetPixel(5, ($bmp.Height - 5))
    $lastRow = $bmp.Height - 1
    for ($y = $bmp.Height - 1; $y -ge 0; $y -= 4) {
        $found = $false
        for ($x = 20; $x -lt $bmp.Width; $x += 40) {
            $p = $bmp.GetPixel($x, $y)
            if ([math]::Abs($p.R - $bg.R) + [math]::Abs($p.G - $bg.G) + [math]::Abs($p.B - $bg.B) -gt 24) { $found = $true; break }
        }
        if ($found) { $lastRow = $y; break }
    }
    $h = [math]::Min($bmp.Height, $lastRow + 30)
    $rect = New-Object System.Drawing.Rectangle(0, 0, $bmp.Width, $h)
    $crop = $bmp.Clone($rect, $bmp.PixelFormat)
    $outPath = Join-Path $repo "$($names[$n]).png"
    $crop.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $crop.Dispose(); $bmp.Dispose()
    Write-Output "$($names[$n]).png  ${h}px"
}
