import HealthKit

struct HealthSnapshot: Codable {
    let heartRate: Double?
    let restingHeartRate: Double?
    let steps: Int?
    let activeCalories: Double?
    let bloodOxygen: Double?
    let sleepHours: Double?
    let sleepDeepMinutes: Int?
    let sleepRemMinutes: Int?
}

class HealthDataProvider {
    private let store = HKHealthStore()

    static let readTypes: Set<HKObjectType> = {
        var types: Set<HKObjectType> = [
            HKQuantityType(.heartRate),
            HKQuantityType(.stepCount),
            HKQuantityType(.activeEnergyBurned),
            HKQuantityType(.oxygenSaturation),
            HKCategoryType(.sleepAnalysis),
            HKQuantityType(.restingHeartRate),
        ]
        return types
    }()

    func requestAuthorization() async -> Bool {
        guard HKHealthStore.isHealthDataAvailable() else { return false }
        do {
            try await store.requestAuthorization(toShare: [], read: Self.readTypes)
            return true
        } catch {
            print("[HealthKit] Authorization failed: \(error)")
            return false
        }
    }

    func fetchSnapshot() async -> HealthSnapshot {
        async let hr = latestQuantity(.heartRate, unit: HKUnit(from: "count/min"))
        async let rhr = latestQuantity(.restingHeartRate, unit: HKUnit(from: "count/min"))
        async let spo2 = latestQuantity(.oxygenSaturation, unit: .percent())
        async let steps = todaySum(.stepCount, unit: .count())
        async let calories = todaySum(.activeEnergyBurned, unit: .kilocalorie())
        async let sleepData = fetchSleep()

        let sleep = await sleepData
        return await HealthSnapshot(
            heartRate: hr,
            restingHeartRate: rhr,
            steps: steps.map { Int($0) },
            activeCalories: calories,
            bloodOxygen: spo2.map { $0 * 100 },
            sleepHours: sleep.totalHours,
            sleepDeepMinutes: sleep.deepMinutes,
            sleepRemMinutes: sleep.remMinutes
        )
    }

    private func latestQuantity(_ type: HKQuantityTypeIdentifier, unit: HKUnit) async -> Double? {
        let quantityType = HKQuantityType(type)
        let predicate = HKQuery.predicateForSamples(
            withStart: Calendar.current.date(byAdding: .hour, value: -24, to: Date()),
            end: Date(),
            options: .strictEndDate
        )
        let descriptor = HKSampleQueryDescriptor(
            predicates: [.quantitySample(type: quantityType, predicate: predicate)],
            sortDescriptors: [SortDescriptor(\.startDate, order: .reverse)],
            limit: 1
        )
        do {
            let results = try await descriptor.result(for: store)
            return results.first?.quantity.doubleValue(for: unit)
        } catch {
            print("[HealthKit] Failed to fetch \(type): \(error)")
            return nil
        }
    }

    private func todaySum(_ type: HKQuantityTypeIdentifier, unit: HKUnit) async -> Double? {
        let quantityType = HKQuantityType(type)
        let startOfDay = Calendar.current.startOfDay(for: Date())
        let predicate = HKQuery.predicateForSamples(
            withStart: startOfDay,
            end: Date(),
            options: .strictStartDate
        )
        let descriptor = HKStatisticsQueryDescriptor(
            predicate: .quantitySample(type: quantityType, predicate: predicate),
            options: .cumulativeSum
        )
        do {
            let result = try await descriptor.result(for: store)
            return result?.sumQuantity()?.doubleValue(for: unit)
        } catch {
            print("[HealthKit] Failed to sum \(type): \(error)")
            return nil
        }
    }

    private struct SleepResult {
        let totalHours: Double?
        let deepMinutes: Int?
        let remMinutes: Int?
    }

    private func fetchSleep() async -> SleepResult {
        let sleepType = HKCategoryType(.sleepAnalysis)
        let yesterday = Calendar.current.date(byAdding: .day, value: -1, to: Calendar.current.startOfDay(for: Date()))!
        let predicate = HKQuery.predicateForSamples(
            withStart: yesterday,
            end: Date(),
            options: .strictEndDate
        )
        let descriptor = HKSampleQueryDescriptor(
            predicates: [.categorySample(type: sleepType, predicate: predicate)],
            sortDescriptors: [SortDescriptor(\.startDate, order: .forward)],
            limit: 100
        )
        do {
            let samples = try await descriptor.result(for: store)
            var totalSeconds: TimeInterval = 0
            var deepSeconds: TimeInterval = 0
            var remSeconds: TimeInterval = 0

            for sample in samples {
                let duration = sample.endDate.timeIntervalSince(sample.startDate)
                let value = sample.value
                // HKCategoryValueSleepAnalysis: asleepCore=3, asleepDeep=4, asleepREM=5
                if value == HKCategoryValueSleepAnalysis.asleepDeep.rawValue {
                    deepSeconds += duration
                    totalSeconds += duration
                } else if value == HKCategoryValueSleepAnalysis.asleepREM.rawValue {
                    remSeconds += duration
                    totalSeconds += duration
                } else if value == HKCategoryValueSleepAnalysis.asleepCore.rawValue {
                    totalSeconds += duration
                } else if value == HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue {
                    totalSeconds += duration
                }
            }

            if totalSeconds == 0 { return SleepResult(totalHours: nil, deepMinutes: nil, remMinutes: nil) }
            return SleepResult(
                totalHours: (totalSeconds / 3600 * 10).rounded() / 10,
                deepMinutes: Int(deepSeconds / 60),
                remMinutes: Int(remSeconds / 60)
            )
        } catch {
            print("[HealthKit] Failed to fetch sleep: \(error)")
            return SleepResult(totalHours: nil, deepMinutes: nil, remMinutes: nil)
        }
    }
}
