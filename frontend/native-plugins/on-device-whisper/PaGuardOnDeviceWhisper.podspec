require 'json'

package = JSON.parse(File.read(File.join(__dir__, 'package.json')))

Pod::Spec.new do |s|
  s.name = 'PaGuardOnDeviceWhisper'
  s.version = package['version']
  s.summary = package['description']
  s.license = package['license']
  s.homepage = 'https://github.com/bargainfactory/priorauthguard'
  s.author = package['author']
  s.source = { :git => 'https://github.com/bargainfactory/priorauthguard.git', :tag => "v#{s.version}" }
  s.source_files = 'ios/Sources/**/*.{swift,h,m}'
  s.ios.deployment_target = '14.0'
  s.dependency 'Capacitor', '~> 6.0'
  # sherpa-onnx-runtime ships Whisper INT8 weights for iOS at ~120 MB.
  # If you prefer whisper.cpp on iOS, swap this dep and adjust the Swift class.
  s.dependency 'sherpa-onnx-runtime', '~> 1.10'
  s.swift_version = '5.9'
end
