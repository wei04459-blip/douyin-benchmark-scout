import Foundation
import Vision
// Input: directory of numbered frames sampled at a known interval. No UI capture.
let args = CommandLine.arguments
if args.count != 4 { fputs("usage: subtitle_ocr frames_directory interval_seconds output.jsonl\n", stderr); exit(2) }
let folder = URL(fileURLWithPath: args[1])
guard let interval = Double(args[2]), interval > 0 else { exit(2) }
let output = args[3]
if FileManager.default.fileExists(atPath: output) { fputs("Output already exists\n",stderr);exit(2) }
FileManager.default.createFile(atPath: output, contents: nil)
let handle = FileHandle(forWritingAtPath: output)!
defer { try? handle.close() }
let files = try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys:nil).filter { $0.pathExtension == "jpg" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
for (index, file) in files.enumerated() {
 try autoreleasepool {
  let request = VNRecognizeTextRequest()
  request.recognitionLevel = .accurate
  request.recognitionLanguages = ["zh-Hans", "en-US"]
  request.usesLanguageCorrection = false
  try VNImageRequestHandler(url:file,options:[:]).perform([request])
  let texts: [[String:Any]] = (request.results ?? []).compactMap { r in
   guard let t = r.topCandidates(1).first else { return nil }
   return ["text":t.string,"confidence":t.confidence,"x":r.boundingBox.minX,"y":r.boundingBox.minY,"width":r.boundingBox.width,"height":r.boundingBox.height]
  }
  let row: [String:Any] = ["time":Double(index)*interval,"frame":file.path,"texts":texts]
  let data=try JSONSerialization.data(withJSONObject:row,options:[.sortedKeys,.withoutEscapingSlashes])
  try handle.write(contentsOf:data);try handle.write(contentsOf:Data([10]))
 }
}
