import CoreLocation
import Foundation

struct WeatherSnapshot: Codable {
    let locationName: String?
    let tempC: Double?
    let feelsLikeC: Double?
    let humidity: Double?
    let conditionDescription: String?
    let todayMaxC: Double?
    let todayMinC: Double?
    let windSpeedKmh: Double?
    let uvIndex: Int?
}

// Open-Meteo API response shapes
private struct OpenMeteoResponse: Decodable {
    let current: OpenMeteoCurrent
    let daily: OpenMeteoDaily
}

private struct OpenMeteoCurrent: Decodable {
    let temperature_2m: Double
    let apparent_temperature: Double
    let relative_humidity_2m: Double
    let weather_code: Int
    let wind_speed_10m: Double
    let uv_index: Double
}

private struct OpenMeteoDaily: Decodable {
    let temperature_2m_max: [Double]
    let temperature_2m_min: [Double]
}

// WMO Weather Code → Chinese description
private func wmoChineseDescription(_ code: Int) -> String {
    switch code {
    case 0: return "晴"
    case 1: return "大部晴"
    case 2: return "多云"
    case 3: return "阴"
    case 45, 48: return "雾"
    case 51, 53, 55: return "小雨"
    case 56, 57: return "冻雨"
    case 61, 63: return "雨"
    case 65: return "大雨"
    case 66, 67: return "雨夹雪"
    case 71, 73: return "雪"
    case 75: return "大雪"
    case 77: return "冰粒"
    case 80, 81: return "阵雨"
    case 82: return "强阵雨"
    case 85, 86: return "阵雪"
    case 95: return "雷暴"
    case 96, 99: return "冰雹"
    default: return "未知"
    }
}

class WeatherDataProvider: NSObject, CLLocationManagerDelegate {
    private let locationManager = CLLocationManager()
    private var locationContinuation: CheckedContinuation<CLLocation?, Never>?

    override init() {
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyKilometer
    }

    func requestAuthorization() {
        locationManager.requestWhenInUseAuthorization()
    }

    /// Returns (latitude, longitude) using only CoreLocation — no HTTPS.
    func fetchCoordinates() async -> (Double, Double)? {
        let location = await requestLocation()
        guard let location else { return nil }
        return (location.coordinate.latitude, location.coordinate.longitude)
    }

    func fetchSnapshot() async -> WeatherSnapshot {
        let location = await requestLocation()
        guard let location else {
            return WeatherSnapshot(
                locationName: nil, tempC: nil, feelsLikeC: nil,
                humidity: nil, conditionDescription: nil,
                todayMaxC: nil, todayMinC: nil, windSpeedKmh: nil, uvIndex: nil
            )
        }

        let lat = location.coordinate.latitude
        let lon = location.coordinate.longitude
        let cityName = await reverseGeocode(location)

        let urlStr = "https://api.open-meteo.com/v1/forecast"
            + "?latitude=\(lat)&longitude=\(lon)"
            + "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,uv_index"
            + "&daily=temperature_2m_max,temperature_2m_min"
            + "&timezone=auto&forecast_days=1"

        guard let url = URL(string: urlStr) else {
            return WeatherSnapshot(
                locationName: cityName, tempC: nil, feelsLikeC: nil,
                humidity: nil, conditionDescription: nil,
                todayMaxC: nil, todayMinC: nil, windSpeedKmh: nil, uvIndex: nil
            )
        }

        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let decoded = try JSONDecoder().decode(OpenMeteoResponse.self, from: data)
            let c = decoded.current
            let d = decoded.daily

            return WeatherSnapshot(
                locationName: cityName,
                tempC: round(c.temperature_2m * 10) / 10,
                feelsLikeC: round(c.apparent_temperature * 10) / 10,
                humidity: round(c.relative_humidity_2m),
                conditionDescription: wmoChineseDescription(c.weather_code),
                todayMaxC: d.temperature_2m_max.first.map { round($0 * 10) / 10 },
                todayMinC: d.temperature_2m_min.first.map { round($0 * 10) / 10 },
                windSpeedKmh: round(c.wind_speed_10m * 10) / 10,
                uvIndex: Int(c.uv_index)
            )
        } catch {
            print("[Weather] Open-Meteo fetch failed: \(error)")
            return WeatherSnapshot(
                locationName: cityName, tempC: nil, feelsLikeC: nil,
                humidity: nil, conditionDescription: nil,
                todayMaxC: nil, todayMinC: nil, windSpeedKmh: nil, uvIndex: nil
            )
        }
    }

    private func requestLocation() async -> CLLocation? {
        if let recent = locationManager.location,
           Date().timeIntervalSince(recent.timestamp) < 300 {
            return recent
        }

        return await withCheckedContinuation { continuation in
            locationContinuation = continuation
            locationManager.requestLocation()
        }
    }

    private func reverseGeocode(_ location: CLLocation) async -> String? {
        let geocoder = CLGeocoder()
        do {
            let placemarks = try await geocoder.reverseGeocodeLocation(location)
            return placemarks.first?.locality
        } catch {
            return nil
        }
    }

    // MARK: - CLLocationManagerDelegate

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        locationContinuation?.resume(returning: locations.last)
        locationContinuation = nil
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        print("[Location] Failed: \(error)")
        locationContinuation?.resume(returning: nil)
        locationContinuation = nil
    }
}
