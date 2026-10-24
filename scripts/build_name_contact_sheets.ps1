param(
    [string]$IndexPath = 'data/weibo/2026-05-26_2026-10-20/人名复核/照片人名_来源索引.json'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$resolvedIndex = (Resolve-Path -LiteralPath $IndexPath).Path
$reviewRoot = Split-Path -Parent $resolvedIndex
$index = Get-Content -LiteralPath $resolvedIndex -Encoding UTF8 -Raw | ConvertFrom-Json
$sheetRoot = Join-Path $reviewRoot 'contact_sheets'
[System.IO.Directory]::CreateDirectory($sheetRoot) | Out-Null
foreach ($picture in $index.pictures) {
    $target = Join-Path $reviewRoot $picture.crop_file
    [System.IO.Directory]::CreateDirectory((Split-Path -Parent $target)) | Out-Null
    $source = [System.Drawing.Bitmap]::new([string]$picture.source_image)
    try {
        $box = $picture.crop_box_relative
        $rect = [System.Drawing.Rectangle]::new(
            [int]($source.Width * $box[0]), [int]($source.Height * $box[1]),
            [int]($source.Width * ($box[2] - $box[0])), [int]($source.Height * ($box[3] - $box[1])))
        $crop = $source.Clone($rect, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
        try { $crop.Save($target, [System.Drawing.Imaging.ImageFormat]::Png) }
        finally { $crop.Dispose() }
    } finally { $source.Dispose() }
}
$groups = $index.pictures | Group-Object season, sheet_group
foreach ($group in $groups) {
    $pictures = @($group.Group)
    $canvas = [System.Drawing.Bitmap]::new(1200, 1560)
    $graphics = [System.Drawing.Graphics]::FromImage($canvas)
    $font = [System.Drawing.Font]::new('Arial', 16)
    try {
        $graphics.Clear([System.Drawing.Color]::WhiteSmoke)
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        for ($position = 0; $position -lt $pictures.Count; $position++) {
            $picture = $pictures[$position]
            $left = ($position % 4) * 300
            $top = [math]::Floor($position / 4) * 520
            $graphics.DrawString("$($picture.picture_id) $($picture.season)", $font,
                [System.Drawing.Brushes]::Black, [single]($left + 12), [single]($top + 6))
            $crop = [System.Drawing.Bitmap]::new((Join-Path $reviewRoot $picture.crop_file))
            try {
                $scale = [math]::Min(280.0 / $crop.Width, 476.0 / $crop.Height)
                $width = [int]($crop.Width * $scale)
                $height = [int]($crop.Height * $scale)
                $destination = [System.Drawing.Rectangle]::new(
                    [int]($left + (300 - $width) / 2), [int]($top + 38), $width, $height)
                $graphics.DrawImage($crop, $destination)
            } finally { $crop.Dispose() }
        }
        $first = $pictures[0]
        $last = $pictures[-1]
        $file = '{0}_组{1:00}_{2}-{3}.png' -f $first.season, [int]$first.sheet_group,
            $first.picture_id, $last.picture_id
        $canvas.Save((Join-Path $sheetRoot $file), [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $font.Dispose()
        $graphics.Dispose()
        $canvas.Dispose()
    }
}
Write-Output "Created $($index.pictures.Count) crops and $($groups.Count) contact sheets in $reviewRoot"
