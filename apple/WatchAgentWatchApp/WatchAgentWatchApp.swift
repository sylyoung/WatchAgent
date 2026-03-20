import AVFoundation
import SwiftUI

@main
struct WatchAgentWatchApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView(viewModel: SessionViewModel(
                apiClient: WatchAgentAPIClient(
                    baseURL: URL(string: "http://192.168.1.16:8787")!
                )
            ))
            .onAppear {
                // Log available zh-CN TTS voices for debugging
                let voices = AVSpeechSynthesisVoice.speechVoices().filter { $0.language.starts(with: "zh") }
                for v in voices {
                    print("[TTS] \(v.name) | \(v.identifier) | quality: \(v.quality.rawValue)")
                }
            }
        }
    }
}
