import AVFoundation
import Combine

/// Persisted voice configuration for TTS playback.
final class VoiceSettings: ObservableObject {
    static let shared = VoiceSettings()

    /// Curated Chinese voice options available on watchOS / iOS.
    struct VoiceOption: Identifiable, Hashable {
        let id: String          // AVSpeechSynthesisVoice identifier
        let label: String       // Human-readable name shown in picker
    }

    /// Cloud voice options matching backend VOICE_OPTIONS (Volcano Engine TTS).
    struct CloudVoiceOption: Identifiable, Hashable {
        let id: String
        let label: String
    }

    static let cloudVoiceOptions: [CloudVoiceOption] = [
        CloudVoiceOption(id: "zh_female_vv_uranus_bigtts",           label: "vivi 2.0 (通用女声)"),
        CloudVoiceOption(id: "saturn_zh_female_cancan_tob",          label: "知性灿灿"),
        CloudVoiceOption(id: "saturn_zh_female_keainvsheng_tob",     label: "可爱女生"),
        CloudVoiceOption(id: "saturn_zh_female_tiaopigongzhu_tob",   label: "调皮公主"),
        CloudVoiceOption(id: "saturn_zh_male_shuanglangshaonian_tob", label: "爽朗少年"),
        CloudVoiceOption(id: "saturn_zh_male_tiancaitongzhuo_tob",   label: "天才同桌"),
    ]

    static let defaultVoiceId = "com.apple.ttsbundle.siri_female_zh-CN_compact"

    /// Friendly labels for known voice identifiers.
    private static let knownLabels: [String: String] = [
        "com.apple.ttsbundle.siri_female_zh-CN_compact": "Siri 女声",
        "com.apple.ttsbundle.siri_male_zh-CN_compact":   "Siri 男声",
        "com.apple.voice.compact.zh-CN.Tingting":        "Tingting",
        "com.apple.voice.compact.zh-CN.Lili":            "Lili",
        "com.apple.voice.enhanced.zh-CN.Tingting":       "Tingting HD",
        "com.apple.voice.enhanced.zh-CN.Lili":           "Lili HD",
        "com.apple.voice.premium.zh-CN.Tingting":        "Tingting Premium",
        "com.apple.voice.premium.zh-CN.Lili":            "Lili Premium",
        "com.apple.ttsbundle.siri_female_zh-TW_compact": "Siri 女声(台)",
        "com.apple.ttsbundle.siri_male_zh-TW_compact":   "Siri 男声(台)",
        "com.apple.voice.compact.zh-TW.Meijia":         "Meijia",
        "com.apple.voice.enhanced.zh-TW.Meijia":        "Meijia HD",
        "com.apple.voice.compact.zh-HK.Sinji":          "Sinji(粤)",
        "com.apple.voice.enhanced.zh-HK.Sinji":         "Sinji HD(粤)",
    ]

    /// All Chinese voices installed on this device, discovered at runtime.
    let availableVoices: [VoiceOption]

    @Published var voiceId: String {
        didSet { UserDefaults.standard.set(voiceId, forKey: "voice_id") }
    }

    /// Speech rate (AVSpeechUtterance.rate). Range roughly 0.3 – 0.65; default 0.52.
    @Published var rate: Float {
        didSet { UserDefaults.standard.set(rate, forKey: "voice_rate") }
    }

    /// Pitch multiplier. Range 0.75 – 1.5; default 1.05.
    @Published var pitch: Float {
        didSet { UserDefaults.standard.set(pitch, forKey: "voice_pitch") }
    }

    /// Whether to use cloud TTS (Volcano Engine) instead of local AVSpeechSynthesizer.
    @Published var useCloudTTS: Bool {
        didSet { UserDefaults.standard.set(useCloudTTS, forKey: "voice_use_cloud_tts") }
    }

    /// Selected cloud voice type identifier.
    @Published var cloudVoiceId: String {
        didSet { UserDefaults.standard.set(cloudVoiceId, forKey: "voice_cloud_voice_id") }
    }

    /// Cloud TTS speed ratio. Range 0.5 – 2.0; default 1.0.
    @Published var cloudSpeedRatio: Double {
        didSet { UserDefaults.standard.set(cloudSpeedRatio, forKey: "voice_cloud_speed_ratio") }
    }

    private init() {
        // Discover all installed Chinese voices (zh-CN, zh-TW, zh-HK)
        let allVoices = AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.starts(with: "zh") }
            .sorted { lhs, rhs in
                // Siri voices first, then enhanced/premium, then compact; within each tier sort by name
                func tier(_ v: AVSpeechSynthesisVoice) -> Int {
                    if v.identifier.contains("siri") { return 0 }
                    if v.identifier.contains("premium") { return 1 }
                    if v.identifier.contains("enhanced") { return 2 }
                    return 3
                }
                let lt = tier(lhs), rt = tier(rhs)
                if lt != rt { return lt < rt }
                return lhs.name < rhs.name
            }

        var available: [VoiceOption] = []
        var seen = Set<String>()
        for voice in allVoices {
            guard !seen.contains(voice.identifier) else { continue }
            seen.insert(voice.identifier)
            let label = Self.knownLabels[voice.identifier] ?? voice.name
            available.append(VoiceOption(id: voice.identifier, label: label))
        }
        self.availableVoices = available

        let savedId = UserDefaults.standard.string(forKey: "voice_id") ?? Self.defaultVoiceId
        // Make sure saved voice is still available
        if available.contains(where: { $0.id == savedId }) {
            self.voiceId = savedId
        } else {
            self.voiceId = available.first?.id ?? Self.defaultVoiceId
        }

        let savedRate = UserDefaults.standard.object(forKey: "voice_rate") as? Float
        self.rate = savedRate ?? 0.52

        let savedPitch = UserDefaults.standard.object(forKey: "voice_pitch") as? Float
        self.pitch = savedPitch ?? 1.05

        self.useCloudTTS = UserDefaults.standard.bool(forKey: "voice_use_cloud_tts")
        self.cloudVoiceId = UserDefaults.standard.string(forKey: "voice_cloud_voice_id") ?? "zh_female_vv_uranus_bigtts"
        let savedSpeedRatio = UserDefaults.standard.object(forKey: "voice_cloud_speed_ratio") as? Double
        self.cloudSpeedRatio = savedSpeedRatio ?? 1.0
    }
}
