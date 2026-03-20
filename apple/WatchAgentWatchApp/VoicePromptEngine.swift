import AVFoundation

@MainActor
final class VoicePromptEngine: NSObject, AVAudioPlayerDelegate {
    private let synth = AVSpeechSynthesizer()
    private var audioPlayer: AVAudioPlayer?
    private var speechQueue: [String] = []
    private var isSpeaking = false

    /// Optional relay client for cloud TTS. Set this before calling speak().
    var relayClient: WatchRelayClient?

    func speak(_ text: String) {
        speechQueue.append(text)
        if !isSpeaking {
            drainQueue()
        }
    }

    /// Stop all current and queued speech immediately.
    func stopAll() {
        speechQueue.removeAll()
        isSpeaking = false
        audioPlayer?.stop()
        audioPlayer = nil
        synth.stopSpeaking(at: .immediate)
    }

    private func drainQueue() {
        guard !speechQueue.isEmpty else {
            isSpeaking = false
            return
        }
        isSpeaking = true
        let text = speechQueue.removeFirst()
        let settings = VoiceSettings.shared

        if settings.useCloudTTS, let relay = relayClient {
            Task { @MainActor in
                await speakWithCloudTTS(text, relay: relay, settings: settings)
            }
        } else {
            speakLocally(text, settings: settings)
        }
    }

    // MARK: - Cloud TTS

    private func speakWithCloudTTS(_ text: String, relay: WatchRelayClient, settings: VoiceSettings) async {
        do {
            let audioData = try await relay.requestTTS(
                text: text,
                voiceType: settings.cloudVoiceId,
                speedRatio: settings.cloudSpeedRatio
            )
            try playAudioData(audioData)
        } catch {
            print("[VoicePromptEngine] Cloud TTS failed: \(error.localizedDescription)")
            drainQueue()
        }
    }

    private func playAudioData(_ data: Data) throws {
        let player = try AVAudioPlayer(data: data)
        player.delegate = self
        self.audioPlayer = player
        player.play()
    }

    // Called when AVAudioPlayer finishes — advance to next queued text
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            self.audioPlayer = nil
            self.drainQueue()
        }
    }

    // MARK: - Local TTS

    private func speakLocally(_ text: String, settings: VoiceSettings) {
        let utterance = AVSpeechUtterance(string: text)

        if let voice = AVSpeechSynthesisVoice(identifier: settings.voiceId) {
            utterance.voice = voice
        } else {
            utterance.voice = AVSpeechSynthesisVoice(language: "zh-CN")
        }

        utterance.rate = settings.rate
        utterance.pitchMultiplier = settings.pitch
        // AVSpeechSynthesizer has its own queue, so just advance immediately
        synth.speak(utterance)
        drainQueue()
    }
}
