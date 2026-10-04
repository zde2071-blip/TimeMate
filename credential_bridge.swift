import Foundation
import Security
let input = FileHandle.standardInput.readDataToEndOfFile()
do {
    let d = try JSONSerialization.jsonObject(with: input) as! [String:String]
    let query: [String:Any] = [kSecClass as String:kSecClassGenericPassword, kSecAttrService as String:"local.school-mail-assistant", kSecAttrAccount as String:d["account"] ?? ""]
    if d["action"] == "save" {
        let bytes = Data((d["secret"] ?? "").utf8)
        var status = SecItemUpdate(query as CFDictionary, [kSecValueData as String:bytes] as CFDictionary)
        if status == errSecItemNotFound {
            var add = query; add[kSecValueData as String] = bytes
            status = SecItemAdd(add as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw NSError(domain:"Keychain",code:Int(status)) }
        print("{}")
    } else {
        var q = query; q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &result)
        if status == errSecItemNotFound { print("{}") }
        else {
            guard status == errSecSuccess, let data = result as? Data else { throw NSError(domain:"Keychain",code:Int(status)) }
            let out = try JSONSerialization.data(withJSONObject:["secret":String(data:data,encoding:.utf8) ?? ""])
            FileHandle.standardOutput.write(out)
        }
    }
} catch { fputs("无法访问 macOS 钥匙串\n",stderr); exit(1) }
