# rmw_zenoh_config

Ubuntu 22.04 / ROS 2 Humble向けのrmw_zenoh router導入・更新用リポジトリ。
中央PCと移動体用PCのROS_DOMAIN_IDは35。各PCにrouterを1つ置き、中央PCに明示接続する構成。

## 前提

- ROS Humble導入済み。全PCでrmw_zenohのバージョンをそろえる。
- 中央VMへのTCP 7447と戻り通信が許可されている。
- NTPによる時刻同期が正常。
- 旧zenoh-bridgeや手動routerが7447を使用していない。
- make install/updateはrouterを起動・再起動する。通信停止可能な時間に実施する。

```bash
sudo apt update
sudo apt install make git python3 iproute2 ros-humble-rmw-zenoh-cpp ros-humble-demo-nodes-cpp netcat-openbsd
```

## インストール

リポジトリを取得したディレクトリで、実際の役割を1つ選んで実行する。
sudoで実行しないこと。

```bash
# 車載PC
make install ROLE=vehicle
# 制御用PC
make install ROLE=control
# 中央VMのみ
make install ROLE=central
```

必要なら `SERVER=192.168.1.70 DOMAIN_ID=35` を追加指定する。
中央は0.0.0.0:7447で待受、ほかは127.0.0.1:7447で待受し中央へ接続する。
multicast無効、gossip有効、multihop無効。

初回導入時に、インストール済みパッケージの標準router設定をコピーする。
ロール設定は `/etc/zenoh/rmw_zenoh_config/deployment.env` に保存する。
インストール後に失敗した場合はログと設定を確認し `make update` で再適用する。

## ROSノードの環境

各ユーザーの `~/.bashrc` の末尾へ一度だけ追加する。旧 `~/zenoh/ros-env.sh` の読み込み行は置き換える。

```bash
if [ -f /etc/zenoh/rmw_zenoh_config/ros-env.sh ]; then
    source /etc/zenoh/rmw_zenoh_config/ros-env.sh
fi
```

```bash
source ~/.bashrc
printenv RMW_IMPLEMENTATION ROS_DOMAIN_ID
ros2 daemon stop
```

期待値：rmw_zenoh_cpp / 35。既存ROSノードは再起動する。
ローカルrouter未起動時はROSノードが起動待ちになる。
ROSノードのsystemd自動起動は本リポジトリの対象外。
そのサービスではROSノード起動前に上記ros-env.shとワークスペースを明示的にsourceする。
必要に応じてUnitに `Requires=rmw-zenoh-router.service` と `After=rmw-zenoh-router.service` を指定する。

## 更新・削除

```bash
git pull --ff-only
make check
make update
make status
make logs
```

`update` はスクリプト・サービスを更新し再起動する。deployment.envとrouter.json5（ACLを含む）は保持する。ROSパッケージ更新は行わない。
設定を変更した場合も `make update` でrouterへ反映できる。Domain ID変更後はROSノードも再起動する。

```bash
# サービスと実行ファイルを削除。設定・ROS環境ファイルは保持
make uninstall
# サービス・実行ファイルに加え、このツールの設定ディレクトリも削除
make purge
```

削除時は .bashrc のsource行も手動で削除する。ROSパッケージ、旧bridge、ほかの /etc/zenoh 配下のファイルには触れない。
uninstall後に再導入する場合は保持された設定を使う `make update` を実行する。

## 機器別denyリスト（d37pxi）

中央routerは全許可を維持する。車載・制御PCには同じ機器プロファイルを選択できる。
機器プロファイルを指定しなければ、このツールはACLを追加しない。

新規導入：

```bash
make install ROLE=vehicle DEVICE=d37pxi
# 制御PCの場合
make install ROLE=control DEVICE=d37pxi
```

既に導入済みなら、再インストールは不要：

```bash
git pull --ff-only
make update
make apply-profile DEVICE=d37pxi
```

`make apply-profile` はローカルの機器プロファイルを置き換えてrouterを再起動する。
既存のdeny-profile.jsonはdeny-profile.json.bakへ保存する（前回バックアップは上書き）。
`make update` は適用済みプロファイルを保持する。

配置先：`/etc/zenoh/rmw_zenoh_config/deny-profile.json`。
配布元：`profiles/d37pxi.json`。

```json
{
  "deny_actions": ["/d37pxi/navigate_to_pose"]
}
```

このActionのsend_goal/get_result/cancel_goal/feedback/statusのデータと、対応する探索情報を、中央への経路のNICで送受信禁止にする。
localhost側の通信は制限しない。`/d37pxi/zenoh/navigate_to_pose` は禁止しない。
対応キー形式はROS Humble rmw_zenoh 0.1.11。異なるバージョンは実装・設定形式の確認が必要。

生成したACLは `ZENOH_CONFIG_OVERRIDE` の `access_control` として適用する。
**プロファイル適用中はrouter.json5内のaccess_control全体を置き換える。手書きACLとの併用・マージは未対応。**
生成対象以外は既定で許可するdeny方式であり、allow listには対応していない。

### NIC自動取得とネットワーク変更

NICはinstall時ではなく **router起動・再起動時** に判定する。
`deployment.env` のSERVERを読み、`ip -j -4 route get SERVER` によりOSが選ぶ経路のdevを取得する。
サーバへの通信でNICを探索する処理ではない。lo・ローカルIP・経路不明はエラーにし、ACLなしでは起動しない。
プロファイル適用時のSERVERはIPv4アドレスを指定する。

- 同じSERVERで別NWへ移動：makeの再実行は不要。サービス再起動でNICを再判定する。
- SERVERのIPが変わった：deployment.envのSERVERを編集してサービスを再起動する。
- 稼働中にNICが変わった：監視で検出するとrouterを終了し、systemdの再試行でACLを再生成する。
- 同じNICで経路が変わった：ACL対象NICは変わらない。接続断は以下の監視対象になる。

```bash
sudo systemctl restart rmw-zenoh-router.service
```

自動判定はACLの対象NICを選ぶだけで、ソケットをNICにbindする処理ではない。
複数経路やVPNを使う場合は切替試験を実施すること。切替検出までの監視間隔は最大10秒程度あるため、厳密な分離境界として扱う場合は別途ネットワーク・認証設計が必要。
中央と同じNICを通るほかのZenoh接続にも、このdenyルールは適用される。

### 中央への到達性と停止・再試行

vehicle/controlは起動前だけTCP到達性を確認する（プロファイル未指定の場合も対象）。centralは自己確認しない。

- 起動前：SERVERのTCP 7447へ接続できなければrouterを起動せず失敗終了する。
- 稼働中：中央へのTCP接続確認は行わない。無線切断や中央停止だけを理由にrouterを終了しない。再接続はZenohに任せる。
- systemdが5秒後に再試行する。中央復旧後にrouterを起動する。
- denyプロファイル適用中のみ、10秒間隔で経路NICを確認する。別NICへの変更が確認できた場合だけ停止・再生成する。経路が一時的に取得できない場合は稼働を継続する。

**中央切断時もローカルrouterは維持する。** NIC変更による再生成時はrouterの再起動が発生する。機体の安全停止はこのツールの対象外。
起動前の確認はTCPポートへの到達性であり、Zenohセッション・ROS通信の健全性の保証ではない。
起動前のプローブはTCP接続後すぐ切断するため、中央側に未完了ハンドシェイクのログが出る場合がある。

### 適用後の検証

実機Ubuntu上で、車載PCと制御PCの両側で確認する。

1. routerログの `ACL: SERVER=..., interface=...` が実際の経路と一致する。
2. 生Actionの遠隔エンドポイントが発見されず、各PC内のAction接続は動作する。
3. 共通Action経由でGoal/Feedback/Result/Cancelが往復する。
4. 他Topicの通信は維持する。
5. 同じNICでネットワークを切断してもrouterが維持され、復旧後に再接続する。起動前から中央に到達できない場合は起動を再試行する。
6. NIC変更後に対象NICが再判定される。

同名Actionの一覧表示だけでは遠隔遮断の証明にならない。ROSノード情報と、制御されたテスト用Actionサーバで通信先を確認する。実機を動かすGoalを疎通確認だけのために送らない。

プロファイルを解除する場合（denyが解除される）：

```bash
sudo mv /etc/zenoh/rmw_zenoh_config/deny-profile.json /etc/zenoh/rmw_zenoh_config/deny-profile.json.disabled
sudo systemctl restart rmw-zenoh-router.service
```

## 動作確認

```bash
systemctl is-enabled rmw-zenoh-router.service
systemctl status rmw-zenoh-router.service
journalctl -u rmw-zenoh-router.service -b -n 50 --no-pager
sudo ss -lntp 'sport = :7447'
```

車載・制御PCから：

```bash
nc -vz -w 3 192.168.1.70 7447
ss -ntp dst 192.168.1.70:7447
```

ESTABはTCP接続の確認。さらに別PC間でtalker/listenerを実行する。
各ターミナルでROS環境を読み込んだ状態で、片側は `ros2 run demo_nodes_cpp talker`、もう片側は `ros2 run demo_nodes_cpp listener`。
役割を入れ替えて双方向を確認し、PC再起動後も再確認する。

時刻エラーが出たら `timedatectl status` を確認する。大きな時刻補正前は制御ノードを停止し、補正後にrouterとROSノードを再起動する。

## 参考

- [rmw_zenoh Humble](https://github.com/ros2/rmw_zenoh/tree/humble)
- [Zenoh access control](https://zenoh.io/docs/manual/access-control/)

本リポジトリの実機検証は利用先Ubuntuで行う。最新値優先のQoS、指令の有効期限、切断時の安全処理はアプリ側でも設計する。

キー形式・ACLの確認元：
- [rmw_zenoh 0.1.11 liveliness_utils.cpp](https://github.com/ros2/rmw_zenoh/blob/0.1.11/rmw_zenoh_cpp/src/detail/liveliness_utils.cpp)
- [rmw_zenoh 0.1.11 vendor](https://github.com/ros2/rmw_zenoh/blob/0.1.11/zenoh_cpp_vendor/CMakeLists.txt)

ローカルテストは生成キー・ルート変更・到達不能時の停止処理を検証する。ROS/Zenohを含む実機統合試験は未実施。
