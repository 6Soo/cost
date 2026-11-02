param([string]$ImagePath, [string]$PdfPath, [ValidateSet('ja','ko')][string]$Language = 'ja')
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 } | Select-Object -First 1
function Await($Operation, $Type) {
    $task = $asTask.MakeGenericMethod($Type).Invoke($null, @($Operation))
    if (-not $task.Wait(25000)) { throw 'OCR_TIMEOUT' }
    return $task.Result
}
function AwaitAction($Operation) {
    $task = [System.WindowsRuntimeSystemExtensions]::AsTask($Operation)
    if (-not $task.Wait(25000)) { throw 'OCR_TIMEOUT' }
    $task.GetAwaiter().GetResult()
}
function New-OcrEngine {
    $lang = [Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]::new($Language)
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
    if ($null -eq $engine) { throw 'OCR_LANGUAGE_UNAVAILABLE' }
    return $engine
}
function Read-Image($Path, $Engine) {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    try {
        $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        if ($decoder.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or $decoder.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) { throw 'OCR_IMAGE_TOO_LARGE' }
        $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        try {
            $result = Await ($Engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            return @{text=($result.Lines | ForEach-Object { $_.Text }) -join "`n"; width=$decoder.PixelWidth; height=$decoder.PixelHeight}
        } finally { $bitmap.Dispose() }
    } finally { $stream.Dispose() }
}
$pageStreams = [System.Collections.Generic.List[object]]::new()
try {
    $engine = New-OcrEngine
    if ($PdfPath) {
        $null = [Windows.Data.Pdf.PdfDocument,Windows.Data.Pdf,ContentType=WindowsRuntime]
        $pdf = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync([IO.Path]::GetFullPath($PdfPath))) ([Windows.Storage.StorageFile])
        $document = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($pdf)) ([Windows.Data.Pdf.PdfDocument])
        if ($document.PageCount -lt 1 -or $document.PageCount -gt 10) { throw 'PDF_PAGE_LIMIT' }
        $pages = @()
        for ($i=0; $i -lt $document.PageCount; $i++) {
            $page = $document.GetPage([uint32]$i)
            $scale = [Math]::Min(2.0, 1800.0 / [Math]::Max($page.Size.Width, $page.Size.Height))
            $options = [Windows.Data.Pdf.PdfPageRenderOptions]::new()
            $options.DestinationWidth = [uint32][Math]::Max(1, [Math]::Round($page.Size.Width * $scale))
            $options.DestinationHeight = [uint32][Math]::Max(1, [Math]::Round($page.Size.Height * $scale))
            $stream = [Windows.Storage.Streams.InMemoryRandomAccessStream]::new()
            $pageStreams.Add($stream)
            AwaitAction ($page.RenderToStreamAsync($stream, $options))
            $stream.Seek(0)
            $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
            $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
            try { $recognized = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult]) }
            finally { $bitmap.Dispose() }
            $stream.Seek(0)
            $reader = [Windows.Storage.Streams.DataReader]::new($stream.GetInputStreamAt(0))
            Await ($reader.LoadAsync([uint32]$stream.Size)) ([uint32]) | Out-Null
            $bytes = [byte[]]::new([int]$stream.Size)
            $reader.ReadBytes($bytes)
            $reader.Dispose()
            if ($bytes.Length -gt 4194304) { throw 'PDF_PAGE_IMAGE_TOO_LARGE' }
            $pages += @{page=($i+1); text=($recognized.Lines | ForEach-Object { $_.Text }) -join "`n"; png=[Convert]::ToBase64String($bytes)}
            $page.Dispose()
        }
        @{pages=$pages} | ConvertTo-Json -Depth 5 -Compress
    } elseif ($ImagePath) {
        $result = Read-Image ([IO.Path]::GetFullPath($ImagePath)) $engine
        @{text=$result.text; width=$result.width; height=$result.height; language=$Language} | ConvertTo-Json -Compress
    } else { throw 'INPUT_REQUIRED' }
} catch {
    [Console]::Error.WriteLine('LOCAL_OCR_FAILED')
    exit 2
} finally {
    foreach ($stream in $pageStreams) { $stream.Dispose() }
}
