import Foundation
#if canImport(Speech)
import Speech
#endif
import AVFoundation
#if os(watchOS)
import WatchKit
#endif

@MainActor
final class SpeechController: ObservableObject {
    enum CaptureState {
        case idle
        case listening
        case processing
    }

    enum SpeechError: Error {
        case dictationUnavailable
        case recognizerUnavailable
        case audioEngineError
        case cancelled
    }

    @Published var captureState: CaptureState = .idle
    @Published var lastTranscript: String = ""
    @Published var diagInfo: String = ""

    /// Suggested quick phrases for the dictation input
    static let quickSuggestions: [String] = [
        "今日日程",
        "工作进展",
        "查看快递",
        "我的消息",
        "健康管理",
        "出行叫车",
    ]

#if canImport(Speech)
    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))
    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var tapInstalled = false

    // chunk-based silence detection
    private var chunkTimer: Timer?
    private var consecutiveSilentChunks = 0
    private var everHadSpeech = false
    private var lastCheckedTranscript = ""
    private let chunkInterval: TimeInterval = 0.6
    private let silenceAfterSpeechChunks = 3   // 1.8s → finishCapture
    private let silenceFromStartChunks = 5      // 3.0s → cancelCapture
#endif

    private var onPartialCallback: ((String) -> Void)?
    private var onFinalCallback: ((String) -> Void)?

    /// Request speech recognition + microphone permission.
    func requestPermission() async -> Bool {
#if canImport(Speech)
        // Check sync status first — on watchOS the async requestAuthorization callback
        // may never fire (it routes through iPhone), causing indefinite hang.
        let currentStatus = SFSpeechRecognizer.authorizationStatus()
        let speechStatus: SFSpeechRecognizerAuthorizationStatus
        if currentStatus == .notDetermined {
            // Request with 4s timeout; fall back to treating as authorized if it hangs
            speechStatus = await withCheckedContinuation { continuation in
                var resumed = false
                SFSpeechRecognizer.requestAuthorization { status in
                    guard !resumed else { return }
                    resumed = true
                    continuation.resume(returning: status)
                }
                // Timeout: if callback doesn't fire within 4s, assume it's authorized
                // (dictation-on devices silently grant without callback on watchOS 26)
                DispatchQueue.main.asyncAfter(deadline: .now() + 4) {
                    guard !resumed else { return }
                    resumed = true
                    continuation.resume(returning: .authorized)
                }
            }
        } else {
            speechStatus = currentStatus
        }
        let speechOK = speechStatus == .authorized
        let audioStatus: Bool
        if speechOK {
            let curMicStatus = AVAudioSession.sharedInstance().recordPermission
            if curMicStatus == .granted {
                audioStatus = true
            } else if curMicStatus == .undetermined {
                audioStatus = await AVAudioSession.sharedInstance().requestRecordPermission()
            } else {
                audioStatus = false
            }
        } else {
            audioStatus = false
        }
        diagInfo = "speech:\(speechStatus.rawValue) mic:\(audioStatus)"
        return speechOK && audioStatus
#else
        return true
#endif
    }

    /// Begin a live speech recognition capture session.
    func startCapture(
        onPartial: @escaping (String) -> Void,
        onFinal: @escaping (String) -> Void
    ) throws {
        guard captureState == .idle else { return }

#if canImport(Speech)
        guard let speechRecognizer else {
            diagInfo = "ERROR: zh-CN recognizer init failed"
            throw SpeechError.recognizerUnavailable
        }
        guard speechRecognizer.isAvailable else {
            diagInfo = "ERROR: zh-CN recognizer not available (no model?)"
            throw SpeechError.recognizerUnavailable
        }
        diagInfo = "recognizer OK, starting audio..."

        // Cancel any previous task
        recognitionTask?.cancel()
        recognitionTask = nil

        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.record, mode: .default, options: .duckOthers)
        try audioSession.setActive(true, options: .notifyOthersOnDeactivation)

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        // Do NOT require on-device — Chinese model may not be available offline
        recognitionRequest = request

        onPartialCallback = onPartial
        onFinalCallback = onFinal

        // Reset chunk state
        consecutiveSilentChunks = 0
        everHadSpeech = false
        lastCheckedTranscript = ""

        recognitionTask = speechRecognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor [weak self] in
                guard let self else { return }

                if let result {
                    let text = result.bestTranscription.formattedString
                    self.lastTranscript = text
                    self.diagInfo = "recognized: \"\(text)\""
                    self.onPartialCallback?(text)

                    if result.isFinal {
                        self.finishCapture()
                    }
                }

                if let error {
                    self.diagInfo = "recognition error: \(error.localizedDescription)"
                    self.finishCapture()
                }
            }
        }

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)
        var tapFired = false
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { [weak self] buffer, _ in
            if !tapFired {
                tapFired = true
                Task { @MainActor [weak self] in
                    self?.diagInfo = "audio tap receiving data ✓"
                }
            }
            self?.recognitionRequest?.append(buffer)
        }
        tapInstalled = true

        audioEngine.prepare()
        try audioEngine.start()
        diagInfo = "audioEngine started ✓"

        captureState = .listening
        startChunkTimer()
#else
        // watchOS: SFSpeechRecognizer is unavailable — use system presentTextInputController
        captureState = .listening
        diagInfo = "presenting dictation…"
        onPartialCallback = onPartial
        onFinalCallback = onFinal

        WKApplication.shared().rootInterfaceController?
            .presentTextInputController(
                withSuggestions: Self.quickSuggestions,
                allowedInputMode: .plain
            ) { [weak self] results in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.captureState = .idle
                    self.diagInfo = results == nil ? "cancelled" : "got input"
                    let text = results?.first as? String ?? ""
                    let callback = self.onFinalCallback
                    self.onPartialCallback = nil
                    self.onFinalCallback = nil
                    callback?(text)
                }
            }
#endif
    }

    /// Called by the view layer when text input (via dictation or keyboard) completes.
    func didReceiveInput(_ text: String) {
        guard !text.isEmpty else {
            captureState = .idle
            return
        }
        captureState = .processing
        lastTranscript = text
        onFinalCallback?(text)
        captureState = .idle
        onFinalCallback = nil
    }

    /// Manual stop (user pressed stop button). Stops audio only — caller reads lastTranscript directly.
    func stopCapture() {
#if canImport(Speech)
        stopAudio()
#endif
        captureState = .idle
        onPartialCallback = nil
        onFinalCallback = nil
    }

    // MARK: - Private

#if canImport(Speech)
    private func startChunkTimer() {
        chunkTimer?.invalidate()
        chunkTimer = Timer.scheduledTimer(withTimeInterval: chunkInterval, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.evaluateChunk()
            }
        }
    }

    private func evaluateChunk() {
        let current = lastTranscript
        if current != lastCheckedTranscript {
            lastCheckedTranscript = current
            consecutiveSilentChunks = 0
            if !current.isEmpty { everHadSpeech = true }
        } else {
            consecutiveSilentChunks += 1
        }

        if everHadSpeech && consecutiveSilentChunks >= silenceAfterSpeechChunks {
            finishCapture()
        } else if !everHadSpeech && consecutiveSilentChunks >= silenceFromStartChunks {
            cancelCapture()
        }
    }

    /// Silence detected after speech — stop audio and send transcript.
    private func finishCapture() {
        stopAudio()

        let text = lastTranscript
        let callback = onFinalCallback
        captureState = .idle
        onPartialCallback = nil
        onFinalCallback = nil

        if !text.isEmpty {
            callback?(text)
        }
    }

    /// Silence from start — stop audio and discard (no callback).
    private func cancelCapture() {
        stopAudio()
        captureState = .idle
        onPartialCallback = nil
        onFinalCallback = nil
    }

    private func stopAudio() {
        chunkTimer?.invalidate()
        chunkTimer = nil
        consecutiveSilentChunks = 0
        everHadSpeech = false
        lastCheckedTranscript = ""

        if audioEngine.isRunning {
            audioEngine.stop()
        }
        if tapInstalled {
            audioEngine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask?.cancel()
        recognitionTask = nil
    }
#endif
}

#if canImport(Speech)
private extension AVAudioSession {
    func requestRecordPermission() async -> Bool {
        await withCheckedContinuation { continuation in
            self.requestRecordPermission { granted in
                continuation.resume(returning: granted)
            }
        }
    }
}
#endif
