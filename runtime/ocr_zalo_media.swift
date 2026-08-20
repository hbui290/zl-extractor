import CoreGraphics
import CryptoKit
import Foundation
import ImageIO
import Vision

struct OCRRecord: Codable {
    let media_timestamp_ms: Int64?
    let relative_path: String
    let content_sha256: String?
    let file_extension: String
    let status: String
    let text: String
    let observation_count: Int
    let mean_confidence: Float
    let error: String?
}

func timestampFromFilename(_ name: String) -> Int64? {
    let first = name.split(separator: "_").first.map(String.init) ?? ""
    return Int64(first)
}

func environmentValue(_ key: String, default defaultValue: String) -> String {
    ProcessInfo.processInfo.environment[key] ?? defaultValue
}

func environmentBool(_ key: String, default defaultValue: Bool) -> Bool {
    let value = environmentValue(key, default: defaultValue ? "1" : "0").lowercased()
    return ["1", "true", "yes", "on"].contains(value)
}

func contentHash(_ file: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: file)
    defer { try? handle.close() }

    var hasher = SHA256()
    while let chunk = try handle.read(upToCount: 1024 * 1024), !chunk.isEmpty {
        hasher.update(data: chunk)
    }
    return hasher.finalize().map { String(format: "%02x", $0) }.joined()
}

func errorRecord(
    file: URL,
    relative: String,
    hash: String?,
    message: String
) -> OCRRecord {
    OCRRecord(
        media_timestamp_ms: timestampFromFilename(file.lastPathComponent),
        relative_path: relative,
        content_sha256: hash,
        file_extension: file.pathExtension.lowercased(),
        status: "error",
        text: "",
        observation_count: 0,
        mean_confidence: 0,
        error: message
    )
}

func loadCachedRecords(_ outputURL: URL) -> [String: OCRRecord] {
    guard let data = try? Data(contentsOf: outputURL) else { return [:] }
    let decoder = JSONDecoder()
    var cached: [String: OCRRecord] = [:]
    for line in data.split(whereSeparator: { $0 == 10 }) {
        guard let record = try? decoder.decode(OCRRecord.self, from: Data(line)),
              let hash = record.content_sha256,
              !hash.isEmpty else { continue }
        cached[record.relative_path] = record
    }
    return cached
}

func recognize(
    file: URL,
    inputDir: URL,
    cached: [String: OCRRecord],
    recognitionLevel: VNRequestTextRecognitionLevel,
    languageCorrection: Bool,
    languages: [String]
) -> OCRRecord {
    let relative = file.path.replacingOccurrences(of: inputDir.path + "/", with: "")
    let hash: String
    do {
        hash = try contentHash(file)
    } catch {
        return errorRecord(file: file, relative: relative, hash: nil, message: String(describing: error))
    }

    if let previous = cached[relative], previous.content_sha256 == hash {
        return previous
    }

    do {
        guard let source = CGImageSourceCreateWithURL(file as CFURL, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
            return errorRecord(file: file, relative: relative, hash: hash, message: "image_decode_failed")
        }

        let request = VNRecognizeTextRequest()
        request.recognitionLevel = recognitionLevel
        request.usesLanguageCorrection = languageCorrection
        if !languages.isEmpty {
            request.recognitionLanguages = languages
        }
        let handler = VNImageRequestHandler(cgImage: image, options: [:])
        try handler.perform([request])

        let observations = request.results ?? []
        let candidates = observations.compactMap { $0.topCandidates(1).first }
        let text = candidates.map(\.string).joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        let confidence = candidates.isEmpty ? 0 : candidates.reduce(Float(0)) { $0 + $1.confidence } / Float(candidates.count)
        return OCRRecord(
            media_timestamp_ms: timestampFromFilename(file.lastPathComponent),
            relative_path: relative,
            content_sha256: hash,
            file_extension: file.pathExtension.lowercased(),
            status: text.isEmpty ? "empty" : "ok",
            text: text,
            observation_count: candidates.count,
            mean_confidence: confidence,
            error: nil
        )
    } catch {
        return errorRecord(file: file, relative: relative, hash: hash, message: String(describing: error))
    }
}

let args = CommandLine.arguments
guard args.count == 3 else {
    fputs("usage: ocr_zalo_media.swift <input-dir> <output-jsonl>\n", stderr)
    exit(2)
}

let inputDir = URL(fileURLWithPath: args[1], isDirectory: true).standardizedFileURL
let outputURL = URL(fileURLWithPath: args[2]).standardizedFileURL
let allowed = Set(["jxl", "jpg", "jpeg", "png", "webp"])
let recognitionLevelName = environmentValue("OCR_RECOGNITION_LEVEL", default: "fast").lowercased()
let recognitionLevel: VNRequestTextRecognitionLevel = recognitionLevelName == "accurate" ? .accurate : .fast
let languageCorrection = environmentBool("OCR_LANGUAGE_CORRECTION", default: false)
let languages = environmentValue("OCR_LANGUAGES", default: "vi-VN,en-US")
    .split(separator: ",")
    .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
    .filter { !$0.isEmpty }
let requestedWorkers = max(1, Int(environmentValue("OCR_WORKERS", default: "2")) ?? 2)

let enumerator = FileManager.default.enumerator(
    at: inputDir,
    includingPropertiesForKeys: [.isRegularFileKey],
    options: [.skipsHiddenFiles]
)
let files = (enumerator?.compactMap { $0 as? URL } ?? [])
    .filter { allowed.contains($0.pathExtension.lowercased()) }
    .sorted { $0.path < $1.path }
let workerCount = max(1, min(requestedWorkers, max(1, files.count)))
let cached = loadCachedRecords(outputURL)

var records = Array<OCRRecord?>(repeating: nil, count: files.count)
let recordsLock = NSLock()
let queue = OperationQueue()
queue.maxConcurrentOperationCount = workerCount
queue.qualityOfService = .utility

for (index, file) in files.enumerated() {
    queue.addOperation {
        let record = recognize(
            file: file,
            inputDir: inputDir,
            cached: cached,
            recognitionLevel: recognitionLevel,
            languageCorrection: languageCorrection,
            languages: languages
        )
        recordsLock.lock()
        records[index] = record
        recordsLock.unlock()
    }
}
queue.waitUntilAllOperationsAreFinished()

var encoder = JSONEncoder()
encoder.outputFormatting = [.withoutEscapingSlashes]
var output = Data()
for record in records.compactMap({ $0 }) {
    if let line = try? encoder.encode(record) {
        output.append(line)
        output.append(10)
    }
}

try output.write(to: outputURL, options: .atomic)
print("files=\(files.count) workers=\(workerCount) recognition=\(recognitionLevelName) cached=\(cached.count) output=\(outputURL.path)")
