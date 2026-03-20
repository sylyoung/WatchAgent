import SwiftUI

struct VoiceSettingsView: View {
    @ObservedObject var settings = VoiceSettings.shared
    @StateObject private var previewer = PreviewEngine()

    var body: some View {
        List {
            Section("云端语音") {
                Toggle("使用云端TTS", isOn: $settings.useCloudTTS)
                if settings.useCloudTTS {
                    Picker("云端音色", selection: $settings.cloudVoiceId) {
                        ForEach(VoiceSettings.cloudVoiceOptions) { voice in
                            Text(voice.label).tag(voice.id)
                        }
                    }
                    HStack {
                        Text("慢")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        Slider(value: $settings.cloudSpeedRatio, in: 0.5 ... 2.0, step: 0.1)
                        Text("快")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    Text(String(format: "语速 %.1fx", settings.cloudSpeedRatio))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .center)
                }
            }

            Section("本地音色") {
                Picker("语音", selection: $settings.voiceId) {
                    ForEach(settings.availableVoices) { voice in
                        Text(voice.label).tag(voice.id)
                    }
                }
            }

            Section("语速") {
                HStack {
                    Text("慢")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Slider(value: $settings.rate, in: 0.3 ... 0.65, step: 0.01)
                    Text("快")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Text(String(format: "%.2f", settings.rate))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
            }

            Section("音调") {
                HStack {
                    Text("低")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Slider(value: $settings.pitch, in: 0.75 ... 1.5, step: 0.05)
                    Text("高")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Text(String(format: "%.2f", settings.pitch))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
            }

            Section {
                Button("试听") {
                    previewer.preview(settings: settings)
                }
            }
        }
        .navigationTitle("播报设置")
    }
}

/// Tiny helper so the AVSpeechSynthesizer lifetime is tied to the view.
@MainActor
private final class PreviewEngine: ObservableObject {
    private let engine: VoicePromptEngine

    init() {
        let e = VoicePromptEngine()
        // Wire up a relay client so cloud TTS preview works
        e.relayClient = WatchRelayClient()
        self.engine = e
    }

    func preview(settings: VoiceSettings) {
        engine.speak("你好，这是当前播报音色和速度的预览。")
    }
}
