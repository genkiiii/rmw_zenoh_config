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
sudo apt install make git ros-humble-rmw-zenoh-cpp ros-humble-demo-nodes-cpp netcat-openbsd
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

## allow list

中央routerは標準設定（ACL無効＝全許可）を基準とする。車載routerで無線側の送受信を制限する。
**このリポジトリの初期状態では車載側も全許可。allow listはまだ有効ではない。**

設定先：`/etc/zenoh/rmw_zenoh_config/router.json5` の `access_control`。
起動スクリプトはトポロジー設定のみ上書きし、このACL設定は保持する。
ACL構文・ROS TopicのZenohキー表現は、導入バージョンを確認して作成する。
Topic名をそのままzenoh-bridge-ros2ddsのallow設定へ書く方式とは異なる。

設計要件：

- localhost側のROS通信は維持する。
- 中央向け経路では必要なTopicデータのみ許可する。
- 探索用liveliness、Service、Actionの関連通信を考慮する。
- 帯域削減には車載側の送信前の制限も必要。中央で受信後に捨てるだけでは削減できない。
- 対象インターフェースはRajant本体の名前ではなく、このUbuntu PCの経路のdev名で確認する。
- 中央全許可はアクセス制御の境界にならない。車載側ルールに加え、中央の接続元ネットワーク制限も適用する。

```bash
dpkg-query -W ros-humble-rmw-zenoh-cpp ros-humble-zenoh-cpp-vendor
ip route get 192.168.1.70
```

この結果と許可対象のTopic名・型・方向・Service/Actionを用意してルールを確定する。
ルール導入時は許可Topic、禁止Topic、ローカル通信、ROS graph、Service/Action、再接続を検証する。

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
