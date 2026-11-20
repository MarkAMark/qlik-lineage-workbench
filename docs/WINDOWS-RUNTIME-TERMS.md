# Windows bundled runtime terms / Windows 内置运行时条款

These terms apply only to Microsoft Distributable Code in the bundled Windows
CPython runtime (including vcruntime140*.dll and linked code in .exe/.dll/.pyd
files). They do not replace the MIT license for Trace, the Python license, or
the separate licenses of other third-party components.

By typing YES in the launcher, or supplying -AcceptRuntimeTerms after reviewing
this document, you agree to the following conditions when using or further
distributing that Microsoft code:

1. Retain all copyright, trademark and patent notices in Microsoft Distributable Code.
2. Do not use Microsoft's trademarks in your program names or imply Microsoft endorsement.
3. Use or distribute that code only for Microsoft operating systems, runtime technologies or application platforms.
4. Do not include that code in malicious, deceptive or unlawful programs.
5. When redistributing it, include the original Windows binary conditions and these terms, and require your distributors and external end users to agree to terms protecting Microsoft Distributable Code at least as much as the applicable Microsoft redistribution requirements. You receive only the rights granted by those requirements; these terms do not grant any additional Microsoft rights.

The original conditions are reproduced in [CPython-LICENSE.txt](./licenses/CPython-LICENSE.txt),
under "Additional Conditions for this Windows binary build", and are also
retained verbatim in runtime/LICENSE.txt in the portable package. The original
conditions control in case of any discrepancy. The runtime and Trace are
provided AS IS, subject to the warranty and liability provisions in their
respective original licenses. No Microsoft endorsement or support is offered.

上述条款仅针对便携包中的 Microsoft 可再分发代码。启动时输入 YES，或在阅读后使用
`-AcceptRuntimeTerms`，表示同意遵守：保留原声明、不暗示微软背书、仅用于微软操作系统／
运行时／应用平台、不用于恶意欺骗或非法程序；再次分发时继续携带原始条款，并要求分发者
与外部最终用户同意至少同等保护的条款。具体授权以英文原始 Windows 二进制条款为准。
这不会把 Trace 的 MIT 代码改成专有许可证，也不代表便携包中的全部组件都是 MIT 或全部开源。

The source distribution contains no Microsoft runtime binaries. Users who prefer
to supply their own Python installation can follow the source setup instructions.
