'''EffectWidget
============

(highly experimental)

Experiment to make an EffectWidget, exposing part of the shader
pipeline so users can write and easily apply their own glsl effects.

Basic idea: Take implementation inspiration from shadertree example,
draw children to Fbo and apply custom shader to a RenderContext.

Effects
-------

An effect is a string representing part of a glsl fragment shader. It
must implement a function :code:`effect` as below::

    vec4 effect( vec4 color, sampler2D texture, vec2 tex_coords, vec2 coords)
    {
        ...
    }

The parameters are:

- **color**: The normal colour of the current pixel (i.e. texture
  sampled at tex_coords)
- **texture**: The texture containing the widget's normal background
- **tex_coords**: The normal texture_coords used to access texture
- **coords**: The pixel indices of the current pixel.

The shader code also has access to two useful uniform variables,
:code:`time` containing the time (in seconds) since the program start,
and :code:`resolution` containing the shape (x pixels, y pixels) of
the widget.

'''

from kivy.clock import Clock
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import (StringProperty, ObjectProperty, ListProperty,
                             NumericProperty)
from kivy.graphics import (RenderContext, Fbo, Color, Rectangle,
                           Translate, PushMatrix, PopMatrix,
                           ClearColor, ClearBuffers)
from kivy.event import EventDispatcher
from kivy.base import EventLoop

Builder.load_string('''
<EffectWidget>:
    canvas:
        Color:
            rgba: 1, 1, 1, 1
        Rectangle:
            texture: self.texture
            pos: self.pos
            size: self.size
''')

shader_header = '''
#ifdef GL_ES
precision highp float;
#endif

/* Outputs from the vertex shader */
varying vec4 frag_color;
varying vec2 tex_coord0;

/* uniform texture samplers */
uniform sampler2D texture0;
'''

shader_uniforms = '''
uniform vec2 resolution;
uniform float time;
'''

shader_footer_trivial = '''
void main (void){
     gl_FragColor = frag_color * texture2D(texture0, tex_coord0);
}
'''

shader_footer_effect = '''
void main (void){
    vec4 normal_color = frag_color * texture2D(texture0, tex_coord0);
    vec4 effect_color = effect(normal_color, texture0, tex_coord0,
                               gl_FragCoord.xy);
    gl_FragColor = effect_color;
}
'''

effect_trivial = '''
vec4 effect(vec4 color, sampler2D texture, vec2 tex_coords, vec2 coords)
{
    return color;
}
'''

effect_monochrome = '''
vec4 effect(vec4 color, sampler2D texture, vec2 tex_coords, vec2 coords)
{
    float mag = 1.0/3.0 * (color.x + color.y + color.z);
    return vec4(mag, mag, mag, color.w);
}
'''

effect_red = '''
vec4 effect(vec4 color, sampler2D texture, vec2 tex_coords, vec2 coords)
{
    return vec4(color.x, 0.0, 0.0, 1.0);
}
'''

effect_green = '''
vec4 effect(vec4 color, sampler2D texture, vec2 tex_coords, vec2 coords)
{
    return vec4(0.0, color.y, 0.0, 1.0);
}
'''

effect_blue = '''
vec4 effect(vec4 color, sampler2D texture, vec2 tex_coords, vec2 coords)
{
    return vec4(0.0, 0.0, color.z, 1.0);
}
'''

effect_invert = '''
vec4 effect(vec4 color, sampler2D texture, vec2 tex_coords, vec2 coords)
{
    return vec4(1.0 - color.xyz, 1.0);
}
'''

effect_mix = '''
vec4 effect(vec4 color, sampler2D texture, vec2 tex_coords, vec2 coords)
{{
    return vec4(color.{}, color.{}, color.{}, 1.0);
}}
'''

effect_blur_h = '''
vec4 effect(vec4 color, sampler2D texture, vec2 tex_coords, vec2 coords)
{{
    float dt = ({} / 4.0) * 1.0 / resolution.x;
    vec4 sum = vec4(0.0);
    sum += texture2D(texture, vec2(tex_coords.x - 4.0*dt, tex_coords.y))
                     * 0.05;
    sum += texture2D(texture, vec2(tex_coords.x - 3.0*dt, tex_coords.y))
                     * 0.09;
    sum += texture2D(texture, vec2(tex_coords.x - 2.0*dt, tex_coords.y))
                     * 0.12;
    sum += texture2D(texture, vec2(tex_coords.x - dt, tex_coords.y))
                     * 0.15;
    sum += texture2D(texture, vec2(tex_coords.x, tex_coords.y))
                     * 0.16;
    sum += texture2D(texture, vec2(tex_coords.x + dt, tex_coords.y))
                     * 0.15;
    sum += texture2D(texture, vec2(tex_coords.x + 2.0*dt, tex_coords.y))
                     * 0.12;
    sum += texture2D(texture, vec2(tex_coords.x + 3.0*dt, tex_coords.y))
                     * 0.09;
    sum += texture2D(texture, vec2(tex_coords.x + 4.0*dt, tex_coords.y))
                     * 0.05;
    return sum;
}}
'''

effect_blur_v = '''
vec4 effect(vec4 color, sampler2D texture, vec2 tex_coords, vec2 coords)
{{
    float dt = ({} / 4.0)
                     * 1.0 / resolution.x;
    vec4 sum = vec4(0.0);
    sum += texture2D(texture, vec2(tex_coords.x, tex_coords.y - 4.0*dt))
                     * 0.05;
    sum += texture2D(texture, vec2(tex_coords.x, tex_coords.y - 3.0*dt))
                     * 0.09;
    sum += texture2D(texture, vec2(tex_coords.x, tex_coords.y - 2.0*dt))
                     * 0.12;
    sum += texture2D(texture, vec2(tex_coords.x, tex_coords.y - dt))
                     * 0.15;
    sum += texture2D(texture, vec2(tex_coords.x, tex_coords.y))
                     * 0.16;
    sum += texture2D(texture, vec2(tex_coords.x, tex_coords.y + dt))
                     * 0.15;
    sum += texture2D(texture, vec2(tex_coords.x, tex_coords.y + 2.0*dt))
                     * 0.12;
    sum += texture2D(texture, vec2(tex_coords.x, tex_coords.y + 3.0*dt))
                     * 0.09;
    sum += texture2D(texture, vec2(tex_coords.x, tex_coords.y + 4.0*dt))
                     * 0.05;
    return sum;
}}
'''

effect_postprocessing = '''
vec4 effect(vec4 color, sampler2D texture, vec2 tex_coords, vec2 coords)
{
    vec2 q = tex_coords * vec2(1, -1);
    vec2 uv = 0.5 + (q-0.5);//*(0.9);// + 0.1*sin(0.2*time));

    vec3 oricol = texture2D(texture,vec2(q.x,1.0-q.y)).xyz;
    vec3 col;

    col.r = texture2D(texture,vec2(uv.x+0.003,-uv.y)).x;
    col.g = texture2D(texture,vec2(uv.x+0.000,-uv.y)).y;
    col.b = texture2D(texture,vec2(uv.x-0.003,-uv.y)).z;

    col = clamp(col*0.5+0.5*col*col*1.2,0.0,1.0);

    //col *= 0.5 + 0.5*16.0*uv.x*uv.y*(1.0-uv.x)*(1.0-uv.y);

    col *= vec3(0.8,1.0,0.7);

    col *= 0.9+0.1*sin(10.0*time+uv.y*1000.0);

    col *= 0.97+0.03*sin(110.0*time);

    float comp = smoothstep( 0.2, 0.7, sin(time) );
    //col = mix( col, oricol, clamp(-2.0+2.0*q.x+3.0*comp,0.0,1.0) );

    return vec4(col,1.0);
}
'''

effect_plasma = '''
vec4 effect(vec4 color, sampler2D texture, vec2 tex_coords, vec2 coords)
{
   float x = coords.x;
   float y = coords.y;
   float mov0 = x+y+cos(sin(time)*2.)*100.+sin(x/100.)*1000.;
   float mov1 = y / resolution.y / 0.2 + time;
   float mov2 = x / resolution.x / 0.2;
   float c1 = abs(sin(mov1+time)/2.+mov2/2.-mov1-mov2+time);
   float c2 = abs(sin(c1+sin(mov0/1000.+time)+sin(y/40.+time)+
                  sin((x+y)/100.)*3.));
   float c3 = abs(sin(c2+cos(mov1+mov2+c2)+cos(mov2)+sin(x/1000.)));
   return vec4( 0.5*(c1 + color.z), 0.5*(c2 + color.x),
                0.5*(c3 + color.y), 1.0);
}
'''

effect_pixelate = '''
vec4 effect(vec4 vcolor, sampler2D texture, vec2 texcoord, vec2 pixel_coords)
{{
    vec2 pixelSize = {} / resolution;

    vec2 xy = floor(texcoord/pixelSize)*pixelSize + pixelSize/2.0;

    return texture2D(texture, xy);
}}
'''

effect_fxaa = '''
vec4 effect( vec4 color, sampler2D buf0, vec2 texCoords, vec2 coords)
{

    vec2 frameBufSize = resolution;

    float FXAA_SPAN_MAX = 8.0;
    float FXAA_REDUCE_MUL = 1.0/8.0;
    float FXAA_REDUCE_MIN = 1.0/128.0;

    vec3 rgbNW=texture2D(buf0,texCoords+(vec2(-1.0,-1.0)/frameBufSize)).xyz;
    vec3 rgbNE=texture2D(buf0,texCoords+(vec2(1.0,-1.0)/frameBufSize)).xyz;
    vec3 rgbSW=texture2D(buf0,texCoords+(vec2(-1.0,1.0)/frameBufSize)).xyz;
    vec3 rgbSE=texture2D(buf0,texCoords+(vec2(1.0,1.0)/frameBufSize)).xyz;
    vec3 rgbM=texture2D(buf0,texCoords).xyz;

    vec3 luma=vec3(0.299, 0.587, 0.114);
    float lumaNW = dot(rgbNW, luma);
    float lumaNE = dot(rgbNE, luma);
    float lumaSW = dot(rgbSW, luma);
    float lumaSE = dot(rgbSE, luma);
    float lumaM  = dot(rgbM,  luma);

    float lumaMin = min(lumaM, min(min(lumaNW, lumaNE), min(lumaSW, lumaSE)));
    float lumaMax = max(lumaM, max(max(lumaNW, lumaNE), max(lumaSW, lumaSE)));

    vec2 dir;
    dir.x = -((lumaNW + lumaNE) - (lumaSW + lumaSE));
    dir.y =  ((lumaNW + lumaSW) - (lumaNE + lumaSE));

    float dirReduce = max(
        (lumaNW + lumaNE + lumaSW + lumaSE) * (0.25 * FXAA_REDUCE_MUL),
        FXAA_REDUCE_MIN);

    float rcpDirMin = 1.0/(min(abs(dir.x), abs(dir.y)) + dirReduce);

    dir = min(vec2( FXAA_SPAN_MAX,  FXAA_SPAN_MAX),
          max(vec2(-FXAA_SPAN_MAX, -FXAA_SPAN_MAX),
          dir * rcpDirMin)) / frameBufSize;

    vec3 rgbA = (1.0/2.0) * (
        texture2D(buf0, texCoords.xy + dir * (1.0/3.0 - 0.5)).xyz +
        texture2D(buf0, texCoords.xy + dir * (2.0/3.0 - 0.5)).xyz);
    vec3 rgbB = rgbA * (1.0/2.0) + (1.0/4.0) * (
        texture2D(buf0, texCoords.xy + dir * (0.0/3.0 - 0.5)).xyz +
        texture2D(buf0, texCoords.xy + dir * (3.0/3.0 - 0.5)).xyz);
    float lumaB = dot(rgbB, luma);

    vec4 return_color;
    if((lumaB < lumaMin) || (lumaB > lumaMax)){
        return_color = vec4(rgbA, color.w);
    }else{
        return_color = vec4(rgbB, color.w);
    }

    return return_color;
}
'''


class EffectBase(EventDispatcher):
    '''The base class for GLSL effects. It simply returns its input.

    See module documentation for more details.

    '''
    glsl = StringProperty(effect_trivial)

    fbo = ObjectProperty(None, allownone=True)

    def __init__(self, *args, **kwargs):
        super(EffectBase, self).__init__(*args, **kwargs)
        self.bind(fbo=self.set_fbo_shader)
        self.bind(glsl=self.set_fbo_shader)

    def set_fbo_shader(self, *args):
        if self.fbo is None:
            return
        self.fbo.set_fs(shader_header + shader_uniforms + self.glsl +
                        shader_footer_effect)


class MonochromeEffect(EffectBase):
    '''Returns its input colours in monochrome.'''
    def __init__(self, *args, **kwargs):
        super(MonochromeEffect, self).__init__(*args, **kwargs)
        self.glsl = effect_monochrome


class InvertEffect(EffectBase):
    '''Inverts the colours in the input.'''
    def __init__(self, *args, **kwargs):
        super(InvertEffect, self).__init__(*args, **kwargs)
        self.glsl = effect_invert


class MixEffect(EffectBase):
    '''Mixes the color channels of the input, (r, g, b) to (b, r, g).'''
    def __init__(self, *args, **kwargs):
        super(MixEffect, self).__init__(*args, **kwargs)
        self.glsl = effect_mix


class ScanlinesEffect(EffectBase):
    '''Adds scanlines to the input.'''
    def __init__(self, *args, **kwargs):
        super(ScanlinesEffect, self).__init__(*args, **kwargs)
        self.glsl = effect_postprocessing


class PixelateEffect(EffectBase):
    '''Pixelates the input according to its
    :attr:`~PixelateEffect.pixel_size`'''
    pixel_size = NumericProperty(10)

    def __init__(self, *args, **kwargs):
        super(PixelateEffect, self).__init__(*args, **kwargs)
        self.do_glsl()

    def on_pixel_size(self, *args):
        self.do_glsl()

    def do_glsl(self):
        self.glsl = effect_pixelate.format(self.pixel_size)


class EffectFromFile(EffectBase):
    source = StringProperty('')

    def on_source(self, instance, value):
        if not value:
            return
        filename = resource_find(self.source)
        if filename is None:
            return Logger.error('Error reading file {filename}'.
                                format(filename=self.source))
        with open(filename) as fileh:
            self.glsl = fileh.read()


class MonochromeEffect(EffectBase):
    '''Returns its input colours in monochrome.'''
    def __init__(self, *args, **kwargs):
        super(MonochromeEffect, self).__init__(*args, **kwargs)
        self.glsl = effect_monochrome


class InvertEffect(EffectBase):
    '''Inverts the colours in the input.'''
    def __init__(self, *args, **kwargs):
        super(InvertEffect, self).__init__(*args, **kwargs)
        self.glsl = effect_invert


class ScanlinesEffect(EffectBase):
    '''Adds scanlines to the input.'''
    def __init__(self, *args, **kwargs):
        super(ScanlinesEffect, self).__init__(*args, **kwargs)
        self.glsl = effect_postprocessing


class ChannelMixEffect(EffectBase):
    '''Mixes the color channels of the input according to the order
    property. Channels may be arbitrarily rearranged or repeated.'''

    order = ListProperty([1, 2, 0])
    '''The new sorted order of the rgb channels. Defaults to [1, 2, 0],
    corresponding to (g, b, r).'''

    def __init__(self, *args, **kwargs):
        super(ChannelMixEffect, self).__init__(*args, **kwargs)
        self.do_glsl()

    def on_size(self, *args):
        self.do_glsl()

    def do_glsl(self):
        letters = [{0: 'x', 1: 'y', 2: 'z'}[i] for i in self.order]
        self.glsl = effect_mix.format(*letters)


class PixelateEffect(EffectBase):
    '''Pixelates the input according to its
    :attr:`~PixelateEffect.pixel_size`'''
    pixel_size = NumericProperty(10)

    def __init__(self, *args, **kwargs):
        super(PixelateEffect, self).__init__(*args, **kwargs)
        self.do_glsl()

    def on_pixel_size(self, *args):
        self.do_glsl()

    def do_glsl(self):
        self.glsl = effect_pixelate.format(float(self.pixel_size))


class HorizontalBlurEffect(EffectBase):
    '''Blurs the input horizontally, with the width given by
    :attr:`~HorizontalBlurEffect.size`.'''
    size = NumericProperty(4.0)

    def __init__(self, *args, **kwargs):
        super(HorizontalBlurEffect, self).__init__(*args, **kwargs)
        self.do_glsl()

    def on_size(self, *args):
        self.do_glsl()

    def do_glsl(self):
        self.glsl = effect_blur_h.format(float(self.size))


class VerticalBlurEffect(EffectBase):
    '''Blurs the input vertically, with the width given by
    :attr:`~VerticalBlurEffect.width`.'''
    size = NumericProperty(4.0)

    def __init__(self, *args, **kwargs):
        super(VerticalBlurEffect, self).__init__(*args, **kwargs)
        self.do_glsl()

    def on_size(self, *args):
        self.do_glsl()

    def do_glsl(self):
        self.glsl = effect_blur_h.format(float(self.size))


class FXAAEffect(EffectBase):
    '''Applies very simple antialiasing via fxaa.'''
    def __init__(self, *args, **kwargs):
        super(FXAAEffect, self).__init__(*args, **kwargs)
        self.glsl = effect_fxaa


class EffectFbo(Fbo):
    def __init__(self, *args, **kwargs):
        super(EffectFbo, self).__init__(*args, **kwargs)
        self.texture_rectangle = None

    def set_fs(self, value):
        # set the fragment shader to our source code
        shader = self.shader
        old_value = shader.fs
        shader.fs = value
        if not shader.success:
            shader.fs = old_value
            raise Exception('failed')


class EffectWidget(BoxLayout):

    fs = StringProperty(None)

    # Texture of the final Fbo
    texture = ObjectProperty(None)

    # Rectangle clearing Fbo
    fbo_rectangle = ObjectProperty(None)

    # List of effect strings
    effects = ListProperty([])

    # One extra Fbo for each effect
    fbo_list = ListProperty([])

    # Effects whose glsl we bound to
    _bound_effects = ListProperty([])

    def __init__(self, **kwargs):
        # Make sure opengl context exists
        EventLoop.ensure_window()

        self.canvas = RenderContext(use_parent_projection=True,
                                    use_parent_modelview=True)

        with self.canvas:
            self.fbo = Fbo(size=self.size)

        with self.fbo.before:
            PushMatrix()
            self.fbo_translation = Translate(-self.x, -self.y, 0)
        with self.fbo:
            Color(0, 0, 0)
            self.fbo_rectangle = Rectangle(size=self.size)
        with self.fbo.after:
            PopMatrix()

        super(EffectWidget, self).__init__(**kwargs)

        Clock.schedule_interval(self.update_glsl, 0)

        self.refresh_fbo_setup()
        Clock.schedule_interval(self.update_fbos, 0)

    def on_pos(self, *args):
        self.fbo_translation.x = -self.x
        self.fbo_translation.y = -self.y

    def on_size(self, *args):
        self.fbo.size = self.size
        self.fbo_rectangle.size = self.size
        self.refresh_fbo_setup()

    def update_glsl(self, *largs):
        time = Clock.get_boottime()
        resolution = [float(size) for size in self.size]
        self.canvas['time'] = time
        self.canvas['resolution'] = resolution
        for fbo in self.fbo_list:
            fbo['time'] = time
            fbo['resolution'] = resolution

    def on_effects(self, *args):
        self.refresh_fbo_setup()

    def update_fbos(self, *args):
        for fbo in self.fbo_list:
            fbo.ask_update()

    def refresh_fbo_setup(self, *args):
        # Add/remove fbos until there is one per effect
        while len(self.fbo_list) < len(self.effects):
            with self.canvas:
                new_fbo = EffectFbo(size=self.size)
            with new_fbo:
                Color(1, 1, 1, 1)
                new_fbo.texture_rectangle = Rectangle(
                    size=self.size)

                new_fbo.texture_rectangle.size = self.size
            self.fbo_list.append(new_fbo)
        while len(self.fbo_list) > len(self.effects):
            old_fbo = self.fbo_list.pop()
            self.canvas.remove(old_fbo)

        # Do resizing etc.
        self.fbo.size = self.size
        self.fbo_rectangle.size = self.size
        for i in range(len(self.fbo_list)):
            self.fbo_list[i].size = self.size
            self.fbo_list[i].texture_rectangle.size = self.size

        # If there are no effects, just draw our main fbo
        if len(self.fbo_list) == 0:
            self.texture = self.fbo.texture
            return

        for i in range(1, len(self.fbo_list)):
            fbo = self.fbo_list[i]
            fbo.texture_rectangle.texture = self.fbo_list[i - 1].texture

        # Build effect shaders
        for effect, fbo in zip(self.effects, self.fbo_list):
            effect.fbo = fbo
            # fbo.set_fs(shader_header + shader_uniforms + effect.glsl +
            #            shader_footer_effect)

        self.fbo_list[0].texture_rectangle.texture = self.fbo.texture
        self.texture = self.fbo_list[-1].texture

    def _update_glsl_bindings(self):
        '''(internal) Bind to the glsl of each effect, or
        unbind if the effect has been removed.'''
        bound_effects = self._bound_effects
        effects = self.effects

        for effect in bound_effects:
            if effect not in effects:
                effect.unbind(glsl=self.refresh_fbo_setup)
        # Remove separately to avoid modifying list during iteration
        bound_effects = [effect for effect in bound_effects if
                         effect in effects]

        for effect in effects:
            if effect not in bound_effects:
                bound_effects.append(effect)
                effect.bind(glsl=self.refresh_fbo_setup)

    def on_fs(self, instance, value):
        # set the fragment shader to our source code
        shader = self.canvas.shader
        old_value = shader.fs
        shader.fs = value
        if not shader.success:
            shader.fs = old_value
            raise Exception('failed')

    def add_widget(self, widget):
        # Add the widget to our Fbo instead of the normal canvas
        c = self.canvas
        self.canvas = self.fbo
        super(EffectWidget, self).add_widget(widget)
        self.canvas = c

    def remove_widget(self, widget):
        # Remove the widget from our Fbo instead of the normal canvas
        c = self.canvas
        self.canvas = self.fbo
        super(EffectWidget, self).remove_widget(widget)
        self.canvas = c

    def clear_widgets(self, children=None):
        # Clear widgets from our Fbo instead of the normal canvas
        c = self.canvas
        self.canvas = self.fbo
        super(EffectWidget, self).clear_widgets(children)
        self.canvas = c
